"""PDF export — renders SPEC.md, PLAN.md, and TASKS.md into a branded PDF.

T-USE-07 / Phase 14. Uses WeasyPrint (no headless browser). The HARNESS
directory is intentionally excluded — PDFs are for human audiences.

Security: the renderer is configured with a `no_network_url_fetcher` that
refuses every non-data URL so a malicious `<img src="https://evil/exfil">`
injected into spec content cannot exfiltrate via the resource loader at
render time (Plan §18.4). Data URLs are permitted because the inline CSS
in `export.html.j2` may rely on them.

Dependencies:
- weasyprint  : HTML/CSS → PDF renderer (cairo/pango bound). The Railway
  Python base image bundles the underlying native libraries.
- jinja2      : template engine.
- markdown    : Markdown → HTML with codehilite (Pygments) extension.
- pygments    : code-block syntax highlighting (used via the markdown
  codehilite extension; classes inlined in the template stylesheet).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Note: weasyprint is imported lazily inside render_pdf so the module loads on
# dev environments without the native pango/cairo/gobject libraries — only
# the actual render path requires them. The Railway Docker image ships the
# native deps via the Dockerfile's apt-get step.

from models import Stage, Workspace
from services.pipeline.export_service import ExportNotReadyError

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
_TEMPLATE_NAME = "export.html.j2"

_STAGE_SECTIONS: tuple[tuple[str, str, str], ...] = (
    # (stage_type, section title, kicker shown above title)
    ("spec", "Specification", "Stage 1 of 3"),
    ("plan", "Implementation Plan", "Stage 2 of 3"),
    ("tasks", "Task List", "Stage 3 of 3"),
)

_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


class _NoNetworkFetch(Exception):
    """Raised when WeasyPrint tries to fetch a non-data URL during render."""


def no_network_url_fetcher(url: str, **_: Any) -> dict[str, Any]:
    """WeasyPrint url_fetcher that refuses every non-`data:` URL.

    Plan §18.4 requires that PDF rendering never trigger an outbound HTTP
    request: a malicious workspace must not be able to exfiltrate via an
    `<img src="https://...">` injected into spec content. Data URLs are
    explicitly allowed so inline-encoded base64 assets in the template
    remain functional.

    `no_network` marker — keep this token in the source for the harness
    contract test that scans for the no-network guard.
    """
    if url.startswith("data:"):
        # Delegate to WeasyPrint's default fetcher for data URLs only.
        from weasyprint import default_url_fetcher

        return default_url_fetcher(url)
    logger.warning("pdf_export_blocked_url_fetch url=%s", url[:120])
    raise _NoNetworkFetch(f"Network fetch blocked: {url[:120]}")


def _render_markdown_to_html(markdown_text: str) -> str:
    """Convert a Markdown string to HTML with codehilite syntax classes."""
    if not markdown_text:
        return ""
    return md.markdown(
        markdown_text,
        extensions=[
            "fenced_code",
            "tables",
            "codehilite",
            "sane_lists",
            "toc",
        ],
        extension_configs={
            "codehilite": {
                "guess_lang": False,
                "css_class": "codehilite",
                "noclasses": False,
            },
        },
        output_format="html5",
    )


def _build_sections(stages: dict[str, Stage]) -> list[dict[str, str]]:
    """Build the per-stage section objects consumed by the template."""
    sections: list[dict[str, str]] = []
    for stage_type, title, kicker in _STAGE_SECTIONS:
        stage = stages.get(stage_type)
        body = (stage.content or "") if stage else ""
        sections.append(
            {
                "stage_type": stage_type,
                "title": title,
                "kicker": kicker,
                "html": _render_markdown_to_html(body),
            }
        )
    return sections


def _coverage_label(coverage_summary: Any) -> str | None:
    """One-line coverage chip text for the cover page, or None if unknown.

    Accepts a pre-computed CoverageSummary (Pydantic model), a plain dict,
    or a string.  The caller is responsible for deriving the value from the
    database — the ORM Workspace model has no coverage_summary attribute
    (it is a computed Pydantic-only field that always returns None when read
    via getattr on an ORM instance).  M-1 — T-183.
    """
    summary = coverage_summary
    if not summary:
        return None
    # Handle Pydantic CoverageSummary objects and duck-typed equivalents.
    pct = getattr(summary, "percent", None)
    if isinstance(pct, (int, float)):
        return f"Harness coverage: {int(pct)}%"
    covered = getattr(summary, "covered", None)
    total = getattr(summary, "total", None)
    if covered is not None and total:
        return f"Harness coverage: {covered}/{total}"
    # Fallback: plain dict (legacy callers).
    if isinstance(summary, dict):
        dict_pct = summary.get("coverage_percent") or summary.get("percent")
        if isinstance(dict_pct, (int, float)):
            return f"Harness coverage: {int(dict_pct)}%"
        dict_covered = summary.get("covered_count") or summary.get("covered")
        dict_total = summary.get("total_count") or summary.get("total")
        if dict_covered is not None and dict_total:
            return f"Harness coverage: {dict_covered}/{dict_total}"
        if "label" in summary:
            return str(summary["label"])
    if isinstance(summary, str):
        return summary
    return None


def _render_pdf_sync(html_text: str) -> bytes:
    """Synchronous WeasyPrint render — must be called via run_in_executor.

    WeasyPrint is CPU-bound and holds the GIL for the full render duration
    (typically 0.5–3 s). Keeping it in a standalone module-level function
    allows the async caller to dispatch it to the default thread pool,
    leaving the event loop free to serve other requests.  C-4 — T-176.

    `no_network` marker — keep this token in the source for the harness
    contract test that scans for the no-network guard.
    """
    # Lazy import — keeps the module loadable on dev boxes without the
    # native cairo/pango libs.
    from weasyprint import HTML

    pdf_bytes = HTML(string=html_text).write_pdf(
        url_fetcher=no_network_url_fetcher,
    )
    if not pdf_bytes:
        # WeasyPrint returns bytes or None on certain failure modes; we
        # treat None as a hard failure so callers don't ship empty PDFs.
        raise RuntimeError("PDF rendering returned no bytes")
    return pdf_bytes


def render_pdf(
    *,
    workspace_name: str,
    provider_label: str,
    stages: dict[str, Stage],
    coverage_label: str | None,
) -> bytes:
    """Pure synchronous render entry point — used by tests without a DB.

    Calling this directly from an async context blocks the event loop; use
    render() instead, which dispatches via run_in_executor.
    """
    template = _jinja_env.get_template(_TEMPLATE_NAME)
    html_text = template.render(
        workspace_name=workspace_name,
        provider_label=provider_label or "—",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        coverage_label=coverage_label,
        sections=_build_sections(stages),
    )
    return _render_pdf_sync(html_text)


async def render(
    workspace_id: UUID, user_id: UUID, db: AsyncSession
) -> tuple[bytes, str]:
    """Render the PDF for the given workspace.

    Returns (pdf_bytes, filename_slug). Raises ExportNotReadyError if any
    of the three user-facing stages are not finalised.
    """
    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = ws_result.scalar_one_or_none()
    if workspace is None or workspace.user_id != user_id:
        raise ExportNotReadyError("Workspace not found")

    stages_result = await db.execute(
        select(Stage).where(Stage.workspace_id == workspace_id)
    )
    stages = {s.type: s for s in stages_result.scalars()}

    # Harness stage must exist for the cover-page coverage chip to be meaningful,
    # but we only require the three user-facing stages to be finalised for the
    # PDF body itself.
    for stage_type in ("spec", "plan", "tasks"):
        stage = stages.get(stage_type)
        if stage is None or stage.status != "finalised":
            raise ExportNotReadyError(
                f"Stage {stage_type!r} is not finalised — PDF export unavailable"
            )

    # Derive coverage_summary explicitly — the ORM Workspace has no such
    # attribute; it is only on the Pydantic response schema.  M-1 — T-183.
    from services.sharing.public_share_service import (  # noqa: PLC0415
        _derive_coverage_summary,
    )

    coverage_summary = await _derive_coverage_summary(workspace_id, db)
    template = _jinja_env.get_template(_TEMPLATE_NAME)
    html_text = template.render(
        workspace_name=workspace.name,
        provider_label=workspace.provider or "—",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        coverage_label=_coverage_label(coverage_summary),
        sections=_build_sections(stages),
    )
    # Dispatch WeasyPrint to the default thread pool so the event loop is not
    # blocked during the CPU-bound render (typically 0.5–3 s).  C-4 — T-176.
    pdf_bytes = await asyncio.get_event_loop().run_in_executor(
        None, _render_pdf_sync, html_text
    )
    slug = _safe_filename_slug(workspace.name)
    return pdf_bytes, slug


def _safe_filename_slug(name: str) -> str:
    """Squash to ASCII-safe filename component; never empty."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in (name or "")
    ).strip("-_")
    return cleaned[:60] or "workspace"

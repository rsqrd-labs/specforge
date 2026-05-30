"""Trusted Storyboard renderer and download artifacts (Phase 20 — T-255).

The renderer owns *all* markup, CSS, and PDF production. LLM output stays
structured content only and never reaches the page as markup: the deck is built
from a codebase-owned Jinja template whose every dynamic value is a structured,
already-sanitised string that Jinja autoescapes. There is no path by which
generated text becomes executable HTML/JS/CSS, a remote asset reference, an
external font, an iframe, or a tracking pixel.

Surfaces (per T-255 req 2):
- ``storyboard.html``            — offline, self-contained keynote deck
- ``storyboard.pdf``            — static PDF of the same deck
- ``speaker-notes.md`` / ``.pdf`` — presenter notes (markdown / rendered PDF)
- ``demo-script.md``            — stored demo script markdown
- ``technical-appendix.md``     — stored technical appendix markdown

Security model:
- Deck text is run through the existing ``sanitize_text`` policy (strips every
  HTML tag, including ``<script>``/``<style>``/event handlers) AND HTML-escaped
  by Jinja autoescape — defence in depth, so injected markup is neither
  preserved nor executable.
- The notes markdown → HTML path (used only for the notes PDF) renders markdown
  then bleach-cleans the result against a strict allow-list: safe formatting
  tags only, ``href`` restricted to http/https/mailto, no ``img`` (so remote
  images / tracking pixels cannot survive), no ``script``/``style``/``iframe``/
  event handlers.
- PDF rendering reuses the shared no-network executor (``render_html_to_pdf``),
  so a render can never trigger an outbound HTTP request.
- The renderer is side-effect-free: it never mutates a Storyboard row or touches
  credits, so a render failure leaves state untouched and charges nothing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bleach
import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.pipeline.pdf_export_service import _safe_filename_slug, render_html_to_pdf
from services.security.sanitizer import sanitize_text

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
_DECK_TEMPLATE = "storyboard.html.j2"
_NOTES_TEMPLATE = "storyboard-notes.html.j2"

_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# CSP applied to the downloaded HTML response (req 7). Mirrors the template's
# embedded <meta> CSP so the policy holds whether the file is opened from disk
# or its bytes are inspected via the API response headers.
HTML_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "frame-ancestors 'none'"
)

# Theme palette colours are validated as #RRGGBB at generation time; we
# re-validate here before inlining into CSS so a malformed value can never break
# out of the colour context. Falls back to brand defaults.
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_REMOTE_REFERENCE_RE = re.compile(
    r"(?i)\bhttps?://[^\s<>'\")]+|//[^\s<>'\")]+"
)
_DEFAULT_ACCENT = "#6d28d9"
_DEFAULT_ACCENT_2 = "#0ea5e9"

_VALID_SOURCES = ("SPEC", "PLAN", "HARNESS", "TASKS")
_ARCH_REVEAL_TYPE = "architecture_reveal"

# Strict allow-list for the markdown→HTML notes path. No img (remote images /
# tracking pixels), no script/style/iframe/object/embed, no event-handler attrs.
_NOTES_ALLOWED_TAGS = [
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "code",
    "pre",
    "blockquote",
    "a",
    "span",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
]
_NOTES_ALLOWED_ATTRS = {
    "a": ["href", "title"],
    "span": ["class"],
    "code": ["class"],
    "pre": ["class"],
    "th": ["align"],
    "td": ["align"],
}
_NOTES_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


# ---------------------------------------------------------------------------
# Filenames (req 9) — derived from a filename-safe slug of the workspace name
# ---------------------------------------------------------------------------

_FILENAME_TEMPLATES: dict[str, str] = {
    "html": "specforge-storyboard-{slug}.html",
    "pdf": "specforge-storyboard-{slug}.pdf",
    "notes-md": "specforge-storyboard-speaker-notes-{slug}.md",
    "notes-pdf": "specforge-storyboard-speaker-notes-{slug}.pdf",
    "demo-script": "specforge-storyboard-demo-script-{slug}.md",
    "appendix": "specforge-storyboard-technical-appendix-{slug}.md",
}


def filename_for(kind: str, workspace_name: str) -> str:
    """Stable, filename-safe download name for *kind* (req 9).

    *kind* is one of the keys in ``_FILENAME_TEMPLATES``; the slug is a sanitised
    component of the workspace name (never empty — falls back to ``workspace``).
    """

    try:
        template = _FILENAME_TEMPLATES[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown storyboard download kind: {kind!r}") from exc
    return template.format(slug=_safe_filename_slug(workspace_name))


# ---------------------------------------------------------------------------
# Deck (HTML + PDF)
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    """Sanitise an arbitrary value to safe plain text (existing policy)."""

    if value is None:
        return ""
    return _REMOTE_REFERENCE_RE.sub("", sanitize_text(str(value))).strip()


def _hex_or(default: str, value: Any) -> str:
    return value if isinstance(value, str) and _HEX_RE.match(value) else default


def _visual_detail(visual: dict[str, Any]) -> str:
    """Build a short, sanitised descriptor from a slide visual's string values.

    The visual object allows extra descriptor keys (they are pure data); we
    surface only string values, never interpret any key as markup, and bound the
    result so a verbose descriptor cannot dominate the slide.
    """

    parts = [
        str(v)
        for k, v in visual.items()
        if k != "kind" and isinstance(v, str) and v.strip()
    ]
    return _clean(" · ".join(parts))[:200]


def _build_deck_context(content: dict[str, Any], workspace_name: str) -> dict[str, Any]:
    theme = content.get("theme") or {}
    palette = theme.get("palette") or []
    accent = _hex_or(_DEFAULT_ACCENT, palette[0] if len(palette) > 0 else None)
    accent_2 = _hex_or(_DEFAULT_ACCENT_2, palette[1] if len(palette) > 1 else None)

    sections: list[dict[str, Any]] = []
    for section in content.get("sections") or []:
        slides: list[dict[str, Any]] = []
        for slide in section.get("slides") or []:
            visual = slide.get("visual") or {}
            slides.append(
                {
                    "headline": _clean(slide.get("headline")),
                    "visible_text": _clean(slide.get("visible_text")),
                    "visual_kind": _clean(visual.get("kind")),
                    "visual_detail": _visual_detail(visual),
                    "sources": [
                        s for s in (slide.get("sources") or []) if s in _VALID_SOURCES
                    ],
                }
            )
        sections.append({"title": _clean(section.get("title")), "slides": slides})

    architecture_layers: list[dict[str, Any]] = []
    for diagram in content.get("diagrams") or []:
        if diagram.get("type") == _ARCH_REVEAL_TYPE:
            for layer in diagram.get("layers") or []:
                architecture_layers.append(
                    {
                        "kind": _clean(layer.get("kind")),
                        "label": _clean(layer.get("label")),
                        "summary": _clean(layer.get("summary")),
                    }
                )
            break

    return {
        "title": _clean(content.get("title")) or _clean(workspace_name) or "Storyboard",
        "motif": _clean(theme.get("motif")),
        "accent_color": accent,
        "accent_color_2": accent_2,
        "sections": sections,
        "architecture_layers": architecture_layers,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def render_deck_html(content: dict[str, Any], workspace_name: str) -> str:
    """Render the offline, self-contained keynote deck to an HTML string."""

    template = _jinja_env.get_template(_DECK_TEMPLATE)
    return template.render(**_build_deck_context(content, workspace_name))


async def render_deck_pdf(content: dict[str, Any], workspace_name: str) -> bytes:
    """Render the keynote deck to PDF via the shared no-network executor."""

    html_text = render_deck_html(content, workspace_name)
    return await render_html_to_pdf(html_text)


# ---------------------------------------------------------------------------
# Speaker notes (markdown → safe HTML → PDF)
# ---------------------------------------------------------------------------


def _markdown_to_safe_html(markdown_text: str) -> str:
    """Render markdown to HTML, then bleach-clean against the strict allow-list.

    This is the only path that turns generated markdown into HTML, so it is the
    one that must defuse ``<script>``, event handlers, iframes, remote images /
    tracking pixels, and ``javascript:`` links. Output is safe to embed.
    """

    if not markdown_text:
        return ""
    rendered = md.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    return bleach.clean(
        rendered,
        tags=_NOTES_ALLOWED_TAGS,
        attributes=_NOTES_ALLOWED_ATTRS,
        protocols=_NOTES_ALLOWED_PROTOCOLS,
        strip=True,
    )


def render_notes_html(notes_md: str, workspace_name: str) -> str:
    """Render the speaker-notes document HTML (used for the notes PDF)."""

    template = _jinja_env.get_template(_NOTES_TEMPLATE)
    return template.render(
        title=_clean(workspace_name) or "Speaker Notes",
        body_html=_markdown_to_safe_html(notes_md),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


async def render_notes_pdf(notes_md: str, workspace_name: str) -> bytes:
    """Render the speaker notes to PDF via the shared no-network executor."""

    html_text = render_notes_html(notes_md, workspace_name)
    return await render_html_to_pdf(html_text)

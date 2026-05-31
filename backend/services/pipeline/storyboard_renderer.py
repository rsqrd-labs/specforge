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
from uuid import UUID

import bleach
import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.observability import (
    get_structured_logger,
    record_storyboard_download,
)
from services.pipeline.pdf_export_service import _safe_filename_slug, render_html_to_pdf
from services.security.sanitizer import sanitize_text

logger = get_structured_logger(__name__)

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
_REMOTE_REFERENCE_RE = re.compile(r"(?i)\bhttps?://[^\s<>'\")]+|//[^\s<>'\")]+")
_DEFAULT_ACCENT = "#6d28d9"
_DEFAULT_ACCENT_2 = "#0ea5e9"

_VALID_SOURCES = ("SPEC", "PLAN", "HARNESS", "TASKS")
_ARCH_REVEAL_TYPE = "architecture_reveal"

# The live deck (StoryboardDeck) renders the architecture reveal as the *visual of
# the Technical Architecture slide itself* — there is no standalone architecture
# page. A page is the architecture slide when its slide type is "architecture" or
# it belongs to the Technical Architecture act, mirroring the frontend predicate.
_ARCH_SLIDE_TYPE = "architecture"
_ARCH_ACT_TITLE = "Technical Architecture"

# Canonical plane order the live deck reveals layers in. We order the *emitted*
# layers by this sequence for visual parity, but — unlike the interactive deck —
# never synthesise placeholders for missing planes: a polished PDF must not carry
# "this layer was not described" filler.
_ARCH_LAYER_SEQUENCE = (
    "client",
    "frontend",
    "api",
    "data",
    "llm",
    "integrations",
    "trust",
    "recovery",
)

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

# Sanitized generated markdown fields handled by this module: speaker_notes,
# demo_script, and technical_appendix.  Remote references such as
# http://example.invalid/asset.png or https://example.invalid/font.css are
# removed from deck text before templating; note PDFs keep only safe links and
# never allow remote images/assets.


def record_download_event(
    *,
    storyboard_id: UUID,
    workspace_id: UUID,
    version: int,
    kind: str,
    public: bool,
    status: str,
    user_id: UUID | None = None,
) -> None:
    """Record a successful Storyboard artifact download without content fields."""

    kind_label = record_storyboard_download(kind, public=public)
    fields: dict[str, Any] = {
        "storyboard_id": str(storyboard_id),
        "workspace_id": str(workspace_id),
        "version": version,
        "action": "download",
        "status": status,
        "kind": kind_label,
        "public": public,
    }
    if user_id is not None:
        fields["user_id"] = str(user_id)
    logger.info("storyboard.downloaded", **fields)


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


# Human label per inert visual.kind — mirrors the live deck's VISUAL_KIND_LABEL so
# the offline package reads the same as the presented deck. The renderer draws the
# visual from the slide's own structured descriptors, never from raw source text.
_VISUAL_KIND_LABEL: dict[str, str] = {
    "hero": "Vision",
    "thesis": "Thesis",
    "product": "Product",
    "walkthrough": "Walkthrough",
    "architecture": "Architecture",
    "trust": "Trust & reliability",
    "closing": "Close",
    "appendix_pointer": "Appendix",
    "diagram_ref": "Diagram",
    "bullets": "Highlights",
    "metric": "Key metric",
}
_VISUAL_POINTS_MAX = 5


def _safe_palette(theme: dict[str, Any]) -> list[str]:
    """Return the validated #RRGGBB palette, or a vivid fallback with range.

    Every colour is re-checked here before it is inlined into CSS so a malformed
    value can never break out of the colour context, and so per-act rotation
    always has at least two distinct hues to cycle.
    """

    raw = theme.get("palette") or []
    cleaned = [c for c in raw if isinstance(c, str) and _HEX_RE.match(c)]
    return cleaned if len(cleaned) >= 2 else [_DEFAULT_ACCENT, _DEFAULT_ACCENT_2]


# Dark base the accents are blended toward when used as *text*, and the luminance
# ceiling a text colour must clear to stay readable on the light card surfaces.
_INK_BASE = (22, 15, 46)  # #160f2e
_INK_MAX_LUMINANCE = 105.0  # 0-255 scale


def _relative_luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _readable_ink(hex_colour: str) -> str:
    """Darken an accent until it is legible as text on a light card.

    The palette accent is used as-is for fills, borders, rails and badges (which
    carry their own contrast), but a pale accent (amber, cyan, mint) used as text
    washes out. We blend the accent toward a dark base, increasing the blend until
    the result clears a luminance ceiling — so the hue survives but the text is
    always readable, whatever palette the model produced.
    """

    if not _HEX_RE.match(hex_colour):
        return "#160f2e"
    r = int(hex_colour[1:3], 16)
    g = int(hex_colour[3:5], 16)
    b = int(hex_colour[5:7], 16)
    for accent_weight in (0.72, 0.55, 0.4, 0.28):
        nr = round(r * accent_weight + _INK_BASE[0] * (1 - accent_weight))
        ng = round(g * accent_weight + _INK_BASE[1] * (1 - accent_weight))
        nb = round(b * accent_weight + _INK_BASE[2] * (1 - accent_weight))
        if _relative_luminance(nr, ng, nb) <= _INK_MAX_LUMINANCE:
            return f"#{nr:02x}{ng:02x}{nb:02x}"
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _visual_points(visual: Any) -> list[str]:
    if not isinstance(visual, dict):
        return []
    for key in ("points", "items", "bullets", "highlights"):
        value = visual.get(key)
        if isinstance(value, list):
            points = [_clean(v) for v in value if isinstance(v, str) and v.strip()]
            if points:
                return points[:_VISUAL_POINTS_MAX]
    return []


def _visual_metric(visual: Any) -> dict[str, str] | None:
    if not isinstance(visual, dict):
        return None
    raw_value = visual.get("value") or visual.get("metric") or visual.get("stat")
    if not isinstance(raw_value, (str, int, float)):
        return None
    raw_label = visual.get("label") or visual.get("caption") or visual.get("unit")
    return {
        "value": _clean(str(raw_value)),
        "label": _clean(raw_label) if isinstance(raw_label, str) else "",
    }


def _order_arch_layers(layers: list[Any]) -> list[dict[str, Any]]:
    """Order the *emitted* architecture layers by the canonical plane sequence.

    Only layers the model actually produced are kept (no placeholder padding) and,
    like the live deck, at most one card per canonical kind — so a duplicated kind
    can never push the grid past the two rows the slide is sized for. Known kinds
    sort into ``_ARCH_LAYER_SEQUENCE`` order; any unknown kind keeps its original
    relative position at the end.
    """

    order = {kind: i for i, kind in enumerate(_ARCH_LAYER_SEQUENCE)}
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        kind = _clean(layer.get("kind"))
        if kind and kind in order:
            if kind in seen:
                continue
            seen.add(kind)
        deduped.append(layer)
    return sorted(
        deduped, key=lambda layer: order.get(_clean(layer.get("kind")), len(order))
    )


def _build_arch_layers(
    content: dict[str, Any], palette: list[str]
) -> list[dict[str, Any]]:
    """Themed, structured architecture layers, or ``[]`` when none were emitted.

    Each layer takes the next palette colour so the planes read as a colourful
    stack, exactly like the live ``ArchitectureReveal``.
    """

    for diagram in content.get("diagrams") or []:
        if diagram.get("type") != _ARCH_REVEAL_TYPE:
            continue
        ordered = _order_arch_layers(diagram.get("layers") or [])
        layers: list[dict[str, Any]] = []
        for index, layer in enumerate(ordered):
            label = _clean(layer.get("label"))
            kind = _clean(layer.get("kind"))
            if not label and not kind:
                continue
            layer_accent = palette[index % len(palette)]
            layer_accent_2 = palette[(index + 1) % len(palette)]
            layers.append(
                {
                    "number": len(layers) + 1,
                    "kind": kind,
                    "label": label,
                    "summary": _clean(layer.get("summary")),
                    "accent": layer_accent,
                    "accent_2": layer_accent_2,
                    "ink": _readable_ink(layer_accent),
                    # White number sits on the badge fill, so the fill itself must
                    # be dark enough — use the ink gradient, not the raw accents.
                    "ink_2": _readable_ink(layer_accent_2),
                }
            )
        return layers
    return []


def _build_deck_context(content: dict[str, Any], workspace_name: str) -> dict[str, Any]:
    theme = content.get("theme") or {}
    palette = _safe_palette(theme)
    accent = palette[0]
    accent_2 = palette[1] if len(palette) > 1 else palette[0]

    # The architecture reveal is rendered as the Technical Architecture slide's own
    # visual (mirroring the live deck), so build its themed layers once and attach
    # them to the matching slide(s) below — there is no standalone architecture page.
    arch_layers = _build_arch_layers(content, palette)

    # One flat list of slide "pages" (each renders to its own A4 page). Every
    # slide carries its act's rotating accent so the printed deck shifts colour
    # act by act, exactly like the live deck.
    pages: list[dict[str, Any]] = []
    slide_no = 0
    for index, section in enumerate(content.get("sections") or []):
        section_title = _clean(section.get("title"))
        act_accent = palette[index % len(palette)]
        act_accent_2 = palette[(index + 1) % len(palette)]
        for slide in section.get("slides") or []:
            visual = slide.get("visual") or {}
            kind = _clean(visual.get("kind")) if isinstance(visual, dict) else ""
            slide_no += 1
            # An architecture slide shows the reveal grid as its visual; fall back
            # to the normal visual when no architecture layers were emitted.
            is_arch_slide = (
                _clean(slide.get("type")) == _ARCH_SLIDE_TYPE
                or section_title == _ARCH_ACT_TITLE
            )
            pages.append(
                {
                    "slide_no": slide_no,
                    "act_no": index + 1,
                    "act_title": section_title,
                    "accent": act_accent,
                    "accent_2": act_accent_2,
                    "ink": _readable_ink(act_accent),
                    "headline": _clean(slide.get("headline")),
                    "visible_text": _clean(slide.get("visible_text")),
                    "visual_label": _VISUAL_KIND_LABEL.get(kind, "Highlight"),
                    "visual_points": _visual_points(visual),
                    "visual_metric": _visual_metric(visual),
                    "architecture": (
                        arch_layers if is_arch_slide and arch_layers else None
                    ),
                    "sources": [
                        s for s in (slide.get("sources") or []) if s in _VALID_SOURCES
                    ],
                }
            )

    return {
        "title": _clean(content.get("title")) or _clean(workspace_name) or "Storyboard",
        "motif": _clean(theme.get("motif")),
        "accent_color": accent,
        "accent_color_2": accent_2,
        # The cover carries white text, so its gradient must be dark regardless of
        # how pale the palette is — use the ink (darkened) accents for the cover.
        "cover_accent": _readable_ink(accent),
        "cover_accent_2": _readable_ink(accent_2),
        "palette": palette,
        "pages": pages,
        "total_slides": len(pages),
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

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
    "html": "thought2build-storyboard-{slug}.html",
    "pdf": "thought2build-storyboard-{slug}.pdf",
    "notes-md": "thought2build-storyboard-speaker-notes-{slug}.md",
    "notes-pdf": "thought2build-storyboard-speaker-notes-{slug}.pdf",
    "demo-script": "thought2build-storyboard-demo-script-{slug}.md",
    "appendix": "thought2build-storyboard-technical-appendix-{slug}.md",
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


# Defensive per-field render caps. The printed page is a fixed 297×210mm canvas
# with ``overflow: hidden`` (deliberate — it prevents one slide splitting across
# two pages), so text that cannot fit must be clamped *for rendering*. Fresh
# generations sit under these caps already; the clamps exist so any historical
# payload shape still renders a complete, un-clipped page. Stored payloads are
# never mutated.
_RENDER_TITLE_MAX_CHARS = 140
_RENDER_HEADLINE_MAX_CHARS = 120
_RENDER_VISIBLE_TEXT_MAX_CHARS = 360
_RENDER_POINT_MAX_CHARS = 90


def _clamp_text(text: str, max_chars: int) -> str:
    """Hard-cap already-sanitised text for rendering, with an ellipsis."""

    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


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
            points = [
                _clamp_text(_clean(v), _RENDER_POINT_MAX_CHARS)
                for v in value
                if isinstance(v, str) and v.strip()
            ]
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


# Canonical human copy per plane, mirroring the frontend LAYER_COPY. A plane the
# model omitted is still drawn with a real architectural label (never apologetic
# filler): the topology graph must show all eight planes to read as a system.
_ARCH_LAYER_COPY: dict[str, str] = {
    "client": "User and client entry points",
    "frontend": "Frontend experience",
    "api": "API and backend services",
    "data": "Data stores and state",
    "llm": "LLM and provider layer",
    "integrations": "External integrations",
    "trust": "Trust boundaries",
    "recovery": "Failure and recovery paths",
}

# --- Topology geometry (mirrors ArchitectureReveal.tsx; trusted code only) ----
# The offline renderer draws the *same* node/edge topology as the live deck's
# static-complete SVG base state. WeasyPrint cannot animate, so it consumes the
# static diagram: solid connectors with arrowheads, a dashed trust boundary, and
# a recovery backplane band. Geometry is integer-only so every path/coordinate is
# an exact value (no float formatting) and is built entirely from trusted code —
# only node labels (escaped text) come from the model.
#
# storyboard-v1.5: the diagram lays out only the planes the product actually has.
# ``_arch_topology_geometry`` is a pure function of the present plane set that
# mirrors ``architectureTopology()`` in ArchitectureReveal.tsx — keep the two
# tables in lockstep. When all eight planes are present it reduces to the
# canonical fixed coordinates below (locked by a parity test), so every legacy
# deck renders byte-identically.
_ARCH_VIEW_W = 960
_ARCH_VIEW_H = 600
_ARCH_NODE_W = 168
_ARCH_NODE_H = 88
_ARCH_BOX_KINDS = ("client", "frontend", "api", "data", "llm", "integrations")
# Canonical full-topology reference: the exact node centres when all eight planes
# are present. The runtime path computes centres from the chain/sink tables below
# and the parity test asserts it reproduces this dict for the all-eight case.
_ARCH_NODE_CENTERS: dict[str, tuple[int, int]] = {
    "client": (104, 300),
    "frontend": (330, 300),
    "api": (556, 300),
    "data": (834, 118),
    "llm": (834, 300),
    "integrations": (834, 482),
}
# Canonical full edge set (client through the three sinks). The runtime derives a
# present-only subset of these; the parity test asserts equality for all-eight.
_ARCH_EDGES = (
    ("client", "frontend"),
    ("frontend", "api"),
    ("api", "data"),
    ("api", "llm"),
    ("api", "integrations"),
)
_ARCH_TRUST_MEMBERS = ("frontend", "api", "data", "llm")
_ARCH_RECOVERY_MEMBERS = ("api", "data", "llm", "integrations")

# Present-subset geometry tables (mirror ArchitectureReveal.tsx). The chain
# client → [frontend] → api sits on the vertical centre; the api sinks hang on a
# fixed column with count-driven y-positions so the fan stays centred.
_ARCH_CHAIN_Y = 300
_ARCH_CHAIN_X_WITH_FRONTEND = {"client": 104, "frontend": 330, "api": 556}
_ARCH_CHAIN_X_WITHOUT_FRONTEND = {"client": 104, "api": 430}
_ARCH_SINK_X = 834
_ARCH_SINK_KINDS = ("data", "llm", "integrations")
_ARCH_SINK_Y_BY_COUNT: dict[int, tuple[int, ...]] = {
    0: (),
    1: (300,),
    2: (180, 420),
    3: (118, 300, 482),
}


def _arch_node_box(cx: int, cy: int) -> tuple[int, int, int, int]:
    return cx - _ARCH_NODE_W // 2, cy - _ARCH_NODE_H // 2, _ARCH_NODE_W, _ARCH_NODE_H


def _arch_edge_path(
    frm_center: tuple[int, int], to_center: tuple[int, int]
) -> tuple[str, tuple[int, int]]:
    """Smooth left-to-right connector; returns the path ``d`` and the end point.

    The end tangent is always horizontal (control point shares the end's y), so
    the arrowhead at the target can be a fixed right-pointing triangle.
    """

    ax, ay = frm_center
    bx, by = to_center
    sx, sy = ax + _ARCH_NODE_W // 2, ay
    ex, ey = bx - _ARCH_NODE_W // 2, by
    dx = max((ex - sx) // 2, 36)
    return f"M {sx} {sy} C {sx + dx} {sy}, {ex - dx} {ey}, {ex} {ey}", (ex, ey)


def _arch_region(
    members: tuple[str, ...], centers: dict[str, tuple[int, int]], pad: int
) -> tuple[int, int, int, int] | None:
    """Bounding box around the *present* members, or ``None`` if < 2 remain.

    A boundary drawn around fewer than two boxes is noise, so an overlay region
    whose product has only one member present is dropped entirely.
    """

    boxes = [_arch_node_box(*centers[kind]) for kind in members if kind in centers]
    if len(boxes) < 2:
        return None
    min_x = min(b[0] for b in boxes) - pad
    min_y = min(b[1] for b in boxes) - pad
    max_x = max(b[0] + b[2] for b in boxes) + pad
    max_y = max(b[1] + b[3] for b in boxes) + pad
    return min_x, min_y, max_x - min_x, max_y - min_y


def _arch_topology_geometry(present: set[str]) -> dict[str, Any]:
    """Deterministic node centres, edges, and overlay regions for present planes.

    Pure function of the present plane set — the offline analogue of
    ``architectureTopology()`` in ArchitectureReveal.tsx. Absent planes are simply
    omitted (no invented boxes); overlay regions render only when their own kind
    is present and they still bound at least two members. The all-eight case
    reduces to ``_ARCH_NODE_CENTERS`` / ``_ARCH_EDGES`` (parity test).
    """

    has_frontend = "frontend" in present
    chain_x = (
        _ARCH_CHAIN_X_WITH_FRONTEND if has_frontend else _ARCH_CHAIN_X_WITHOUT_FRONTEND
    )
    centers: dict[str, tuple[int, int]] = {}
    for kind in ("client", "frontend", "api"):
        if kind in present and kind in chain_x:
            centers[kind] = (chain_x[kind], _ARCH_CHAIN_Y)
    present_sinks = [kind for kind in _ARCH_SINK_KINDS if kind in present]
    ys = _ARCH_SINK_Y_BY_COUNT.get(len(present_sinks), ())
    for index, kind in enumerate(present_sinks):
        centers[kind] = (_ARCH_SINK_X, ys[index] if index < len(ys) else _ARCH_CHAIN_Y)

    edges: list[tuple[str, str]] = []
    if has_frontend:
        if "client" in centers and "frontend" in centers:
            edges.append(("client", "frontend"))
        if "frontend" in centers and "api" in centers:
            edges.append(("frontend", "api"))
    elif "client" in centers and "api" in centers:
        edges.append(("client", "api"))
    if "api" in centers:
        edges.extend(("api", sink) for sink in present_sinks)

    trust = (
        _arch_region(_ARCH_TRUST_MEMBERS, centers, 24) if "trust" in present else None
    )
    recovery = (
        _arch_region(_ARCH_RECOVERY_MEMBERS, centers, 38)
        if "recovery" in present
        else None
    )
    return {"centers": centers, "edges": edges, "trust": trust, "recovery": recovery}


def _wrap_label(text: str, width: int = 20, max_lines: int = 2) -> list[str]:
    """Word-wrap a node label to at most ``max_lines`` of ~``width`` chars.

    SVG ``<text>`` does not wrap; we wrap in code and hard-cap each line (with an
    ellipsis when content is dropped) so a long label can never overflow a node.
    """

    text = text.strip()
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    consumed = 0
    for word in words:
        candidate = (current + " " + word).strip()
        if not current or len(candidate) <= width:
            current = candidate
            consumed += 1
        elif len(lines) < max_lines - 1:
            lines.append(current)
            current = word
            consumed += 1
        else:
            break
    if current:
        lines.append(current)
    capped: list[str] = []
    for index, line in enumerate(lines):
        dropped = index == len(lines) - 1 and consumed < len(words)
        if len(line) > width or dropped:
            line = line[: width - 1].rstrip() + "…"
        capped.append(line)
    return capped


def _build_arch_topology(
    content: dict[str, Any], palette: list[str]
) -> dict[str, Any] | None:
    """Build the static architecture topology, or ``None`` when none was emitted.

    Mirrors the live ``ArchitectureReveal`` SVG: the present box nodes, directed
    edges between them, and the trust/recovery overlay regions when those planes
    are present. storyboard-v1.5: only the planes the product actually has are
    drawn — an absent frontend/llm/integrations plane is omitted, never invented
    or filled with apologetic placeholder copy. Node/region labels are the only
    model-derived strings; they are sanitised here and HTML-escaped by the
    template's autoescape.
    """

    diagram: dict[str, Any] | None = None
    for candidate in content.get("diagrams") or []:
        if isinstance(candidate, dict) and candidate.get("type") == _ARCH_REVEAL_TYPE:
            diagram = candidate
            break
    if diagram is None:
        return None

    by_kind: dict[str, dict[str, Any]] = {}
    extras_raw: list[dict[str, Any]] = []
    for layer in diagram.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        kind = _clean(layer.get("kind"))
        if kind in _ARCH_LAYER_COPY:
            by_kind.setdefault(kind, layer)
        elif kind:
            extras_raw.append(layer)

    geometry = _arch_topology_geometry(set(by_kind))
    centers: dict[str, tuple[int, int]] = geometry["centers"]

    def label_for(kind: str) -> str:
        layer = by_kind.get(kind)
        if layer:
            label = _clean(layer.get("label"))
            if label:
                return label
        return _ARCH_LAYER_COPY[kind]

    def accent_for(kind: str) -> str:
        return palette[_ARCH_LAYER_SEQUENCE.index(kind) % len(palette)]

    nodes: list[dict[str, Any]] = []
    for kind in _ARCH_BOX_KINDS:
        if kind not in centers:
            continue
        x, y, w, h = _arch_node_box(*centers[kind])
        accent = accent_for(kind)
        nodes.append(
            {
                "kind": kind,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "accent": accent,
                "ink": _readable_ink(accent),
                "text_x": x + 14,
                "kind_y": y + 24,
                "label_y0": y + 46,
                "label_lines": _wrap_label(label_for(kind)),
            }
        )

    edges: list[dict[str, Any]] = []
    for frm, to in geometry["edges"]:
        d, (ex, ey) = _arch_edge_path(centers[frm], centers[to])
        accent = accent_for(to)
        edges.append(
            {
                "d": d,
                "stroke": accent,
                "arrow_fill": _readable_ink(accent),
                "arrow": f"{ex},{ey} {ex - 10},{ey - 6} {ex - 10},{ey + 6}",
            }
        )

    trust: dict[str, Any] | None = None
    if geometry["trust"] is not None:
        tx, ty, tw, th = geometry["trust"]
        trust_accent = palette[1 % len(palette)]
        trust = {
            "x": tx,
            "y": ty,
            "w": tw,
            "h": th,
            "stroke": trust_accent,
            "label": label_for("trust"),
            "label_x": tx + 16,
            "label_y": ty + 22,
            "label_fill": _readable_ink(trust_accent),
        }

    recovery: dict[str, Any] | None = None
    if geometry["recovery"] is not None:
        rx, ry, rw, rh = geometry["recovery"]
        recovery_accent = palette[2 % len(palette)]
        recovery = {
            "x": rx,
            "y": ry,
            "w": rw,
            "h": rh,
            "fill": recovery_accent,
            "stroke": recovery_accent,
            "label": label_for("recovery"),
            "label_x": rx + 16,
            "label_y": ry + rh - 14,
            "label_fill": _readable_ink(recovery_accent),
        }

    extras: list[dict[str, Any]] = []
    for index, layer in enumerate(extras_raw):
        label = _clean(layer.get("label")) or _clean(layer.get("kind")) or "annotation"
        extras.append(
            {
                "x": 24,
                "y": 444 + index * 52,
                "w": 184,
                "h": 44,
                "label": label[:40],
            }
        )

    return {
        "view_w": _ARCH_VIEW_W,
        "view_h": _ARCH_VIEW_H,
        "nodes": nodes,
        "edges": edges,
        "trust": trust,
        "recovery": recovery,
        "extras": extras,
    }


def _build_deck_context(content: dict[str, Any], workspace_name: str) -> dict[str, Any]:
    theme = content.get("theme") or {}
    palette = _safe_palette(theme)
    accent = palette[0]
    accent_2 = palette[1] if len(palette) > 1 else palette[0]

    # The architecture reveal is rendered as the Technical Architecture slide's own
    # visual (mirroring the live deck), so build the topology graph once and attach
    # it to the matching slide(s) below — there is no standalone architecture page.
    arch_topology = _build_arch_topology(content, palette)

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
            # An architecture slide shows the topology graph as its visual; fall
            # back to the normal visual when no architecture diagram was emitted.
            is_arch_slide = (
                _clean(slide.get("type")) == _ARCH_SLIDE_TYPE
                or section_title == _ARCH_ACT_TITLE
            )
            # ``slide.sources`` stays in the payload (it feeds the SourceLayer
            # overlay and grounding validation) but is deliberately not passed
            # to the template: a launch keynote never prints its audit trail.
            pages.append(
                {
                    "slide_no": slide_no,
                    "act_no": index + 1,
                    "act_title": section_title,
                    "accent": act_accent,
                    "accent_2": act_accent_2,
                    "ink": _readable_ink(act_accent),
                    "headline": _clamp_text(
                        _clean(slide.get("headline")), _RENDER_HEADLINE_MAX_CHARS
                    ),
                    "visible_text": _clamp_text(
                        _clean(slide.get("visible_text")),
                        _RENDER_VISIBLE_TEXT_MAX_CHARS,
                    ),
                    "visual_label": _VISUAL_KIND_LABEL.get(kind, "Highlight"),
                    "visual_points": _visual_points(visual),
                    "visual_metric": _visual_metric(visual),
                    "architecture": (
                        arch_topology if is_arch_slide and arch_topology else None
                    ),
                }
            )

    return {
        "title": _clamp_text(
            _clean(content.get("title")) or _clean(workspace_name) or "Storyboard",
            _RENDER_TITLE_MAX_CHARS,
        ),
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

"""Storyboard prompt builder and strict payload schema (Phase 20 — T-253).

This module owns two things:

1. The **strict structured-output schema** the LLM must produce — a set of
   Pydantic models (``StoryboardPayload`` and friends) that mirror, and are kept
   aligned with, ``harness/schemas/storyboard-payload.schema.json``. The schema
   is the security boundary: the model returns structured data only. It can never
   return HTML, CSS, JavaScript, ``<script>``, iframes, external fonts, remote
   assets, or tracking pixels — the trusted renderer (T-255) owns all markup.
2. The **local, in-code prompt** (system + user + repair). Per V1 the Storyboard
   prompt is never loaded from Langfuse — a remote-editable launch-keynote prompt
   is an unacceptable injection surface — so it lives here as code.

The parse/validate flow (``parse_and_validate_payload``) gives invalid output
exactly one internal repair attempt before raising a typed
``StoryboardPayloadError`` for T-254 to mark the Storyboard failed and refund.
Generated text is treated as untrusted even after it validates: validation
guarantees shape, not safety, and rendering still escapes everything.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)

from prompts.base import SECURITY_AND_PRIVACY_RULES, wrap_untrusted_content
from services.pipeline.storyboard_source import StoryboardSourcePackage

STORYBOARD_PROMPT_VERSION = "storyboard-v1.5"

# The main keynote has exactly six visible top-level acts, in this exact order.
# Validation and Execution Plan are deliberately NOT acts — they belong in the
# technical appendix / demo, never on the main deck.
REQUIRED_SECTION_TITLES: tuple[str, ...] = (
    "Opening Thesis",
    "Product Vision",
    "Product Walkthrough",
    "Technical Architecture",
    "Trust, Security, Reliability",
    "Launch Close",
)
FORBIDDEN_TOP_LEVEL_ACTS: frozenset[str] = frozenset({"Validation", "Execution Plan"})

ARCHITECTURE_REVEAL_TYPE = "architecture_reveal"
# The architecture-reveal diagram is drawn from a closed vocabulary of planes, not
# a fixed quota (storyboard-v1.5). Three planes are universal to every product — an
# actor/client, the compute/API, and the data/state store — so they are always
# required. The rest are OPTIONAL: they render only when the SPEC/PLAN actually
# describes such a component, so a CLI, batch job, or library with no browser UI /
# no model calls / no third-party services is never forced to fabricate a
# frontend / llm / integrations plane to pass validation. All eight kinds remain
# valid; the geometry (both renderers) lays out only the present subset.
CORE_ARCHITECTURE_LAYERS: tuple[str, ...] = ("client", "api", "data")
OPTIONAL_ARCHITECTURE_LAYERS: tuple[str, ...] = (
    "frontend",
    "llm",
    "integrations",
    "trust",
    "recovery",
)
# Full canonical reveal order (client through recovery) — the layer vocabulary and
# the order both renderers reveal present planes in.
ARCHITECTURE_LAYER_KINDS: tuple[str, ...] = (
    "client",
    "frontend",
    "api",
    "data",
    "llm",
    "integrations",
    "trust",
    "recovery",
)
ALLOWED_VISUAL_KINDS: tuple[str, ...] = (
    "hero",
    "thesis",
    "product",
    "walkthrough",
    "architecture",
    "trust",
    "closing",
    "appendix_pointer",
    "diagram_ref",
    "bullets",
    "metric",
)

_SOURCE_ENUM = ("SPEC", "PLAN", "HARNESS", "TASKS")

# Speaker-note depth floor (storyboard-v1.4). A modest minimum keeps stub notes
# ("Talk about the product.") from validating; the prompt asks for ~80-160 words.
# Enforced on fresh generations; grandfathered for carried-over notes when a
# caller passes ``context={GRANDFATHER_NOTE_DEPTH: True}`` (section regeneration
# of a pre-v1.4 Storyboard re-validates the whole spliced payload).
_TALK_TRACK_MIN_CHARS = 120
_BACKUP_POINTS_MIN = 2
# The single context flag that grandfathers ALL fresh-generation content floors
# (note depth AND the P3.4 slide-substance floor) for spliced/legacy payloads.
# Section regeneration splices a freshly generated act into an existing deck and
# re-validates the whole payload with this flag set, so acts authored under an
# older prompt never fail a floor tightened after they were written. Fresh
# generations pass no context, so every floor still gates them.
GRANDFATHER_NOTE_DEPTH = "grandfather_note_depth"

_ID_PATTERN = r"^[a-z0-9-]+$"
_MAX_EXCERPT_CHARS = 1200
_MAX_HEADLINE_WORDS = 18
_MAX_VISIBLE_WORDS = 45
_FORBIDDEN_VIDEO_DEMO_RE = re.compile(
    r"\b(video|recorded|recording)\s+(demo|demonstration|walkthrough)\b|"
    r"\b(demo|demonstration|walkthrough)\s+video\b",
    re.IGNORECASE,
)
_FORBIDDEN_MARKETING_RE = re.compile(
    r"\b("
    r"empower your business|"
    r"join the revolution|"
    r"operational excellence|"
    r"game[- ]changing|"
    r"revolutioni[sz]e|"
    r"transform your|"
    r"seamless workflow automation"
    r")\b",
    re.IGNORECASE,
)
_GENERIC_TITLES = {
    "product launch keynote",
    "launch keynote",
    "product keynote",
    "storyboard keynote",
    "product launch deck",
}
_PLACEHOLDER_WORKSPACE_RE = re.compile(
    r"^(test|untitled|workspace|new workspace|draft)(\s+\d+)?$",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------


class SourceRef(BaseModel):
    """A bounded citation back to a finalised SPEC/PLAN/HARNESS/TASKS source."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=r"^(SPEC|PLAN|HARNESS|TASKS)$")
    source_id: str = Field(min_length=1, max_length=160)
    excerpt: str = Field(min_length=1, max_length=_MAX_EXCERPT_CHARS)


class SpeakerNote(BaseModel):
    """Per-slide presenter guidance — the deck stays sparse, depth lives here."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1, max_length=80)
    talk_track: str = Field(min_length=1)
    transition: str = Field(min_length=1)
    timing_seconds: int = Field(ge=5, le=600)
    pause_cue: str = Field(min_length=1)
    demo_cue: str = ""
    backup_points: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_notes(self, info: ValidationInfo) -> "SpeakerNote":
        # Depth floor (storyboard-v1.4): the deck stays sparse, so presenter depth
        # must live in the talk track and Q&A backups. The floor is enforced on
        # freshly generated notes but grandfathered when a caller validates a
        # spliced payload that carries over notes written under an older prompt
        # (see ``GRANDFATHER_NOTE_DEPTH``) — tightening it must never break
        # section regeneration on a pre-v1.4 Storyboard.
        if not (info.context or {}).get(GRANDFATHER_NOTE_DEPTH):
            if len(self.talk_track) < _TALK_TRACK_MIN_CHARS:
                raise ValueError(
                    f"talk_track must be at least {_TALK_TRACK_MIN_CHARS} characters"
                )
            if len(self.backup_points) < _BACKUP_POINTS_MIN:
                raise ValueError(
                    f"backup_points must have at least {_BACKUP_POINTS_MIN} entries"
                )
        if _FORBIDDEN_VIDEO_DEMO_RE.search(self.demo_cue):
            raise ValueError("demo_cue must not request or describe a video demo")
        for field_name, text in (
            ("talk_track", self.talk_track),
            ("transition", self.transition),
            ("pause_cue", self.pause_cue),
            ("demo_cue", self.demo_cue),
        ):
            if _FORBIDDEN_MARKETING_RE.search(text):
                raise ValueError(f"{field_name} contains generic launch-copy filler")
        for point in self.backup_points:
            if not point.strip():
                raise ValueError("backup_points entries must be non-empty")
            if _FORBIDDEN_VIDEO_DEMO_RE.search(point):
                raise ValueError("backup_points must not request a video demo")
            if _FORBIDDEN_MARKETING_RE.search(point):
                raise ValueError("backup_points contain generic launch-copy filler")
        return self


class StoryboardVisual(BaseModel):
    """Structured visual descriptor for a slide.

    ``kind`` names an inert layout the renderer understands (e.g. ``hero``,
    ``bullets``, ``metric``, ``diagram_ref``). Extra descriptor keys are allowed
    to match the contract, but they are pure data: the renderer escapes every
    value and never interprets any field as markup or executable instructions.
    """

    model_config = ConfigDict(extra="allow")

    kind: str = Field(min_length=1)

    @model_validator(mode="after")
    def _supported_visual_kind(self) -> "StoryboardVisual":
        if self.kind not in ALLOWED_VISUAL_KINDS:
            raise ValueError(
                "visual.kind must be one of: " + ", ".join(ALLOWED_VISUAL_KINDS)
            )
        return self


# Slide types whose whole purpose is to convey product/technical substance. A
# slide of one of these types must carry a real visual descriptor — a non-empty
# ``points`` list or a ``metric``/``value`` — not a bare decorative visual
# (storyboard-v1.5 P3.4). Enforced on fresh generations only; grandfathered for
# spliced/legacy payloads via ``GRANDFATHER_NOTE_DEPTH`` (see the floor below).
_SUBSTANCE_SLIDE_TYPES: frozenset[str] = frozenset({"product", "walkthrough", "trust"})


def visual_has_substance(visual: "StoryboardVisual") -> bool:
    """Whether *visual* carries real content, not just a bare ``kind``.

    Substance is a non-empty ``points`` list (any entry with visible text) or a
    non-empty ``metric``/``value`` descriptor. This is the single definition of
    "substance" shared by the fresh-generation slide floor (P3.4, in this module)
    and the deterministic deck quality gate (P3.5, ``storyboard_quality``), so the
    two never drift.
    """

    extra = visual.__pydantic_extra__ or {}
    points = extra.get("points")
    if isinstance(points, (list, tuple)) and any(str(p).strip() for p in points):
        return True
    for key in ("metric", "value"):
        val = extra.get(key)
        if isinstance(val, bool):
            continue
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, (int, float)):
            return True
        if isinstance(val, (list, tuple, dict)) and len(val) > 0:
            return True
    return False


class StoryboardSlide(BaseModel):
    """One idea per slide. Headline <= 18 words, visible text sparse."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=_ID_PATTERN)
    type: str = Field(
        pattern=r"^(hero|thesis|product|walkthrough|architecture|trust|closing|appendix_pointer)$"
    )
    headline: str = Field(min_length=1, max_length=140)
    visible_text: str = Field(max_length=360)
    visual: StoryboardVisual
    speaker_notes_ref: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _enforce_sparse_and_sources(self, info: ValidationInfo) -> "StoryboardSlide":
        for field_name, text in (
            ("headline", self.headline),
            ("visible_text", self.visible_text),
        ):
            if _FORBIDDEN_MARKETING_RE.search(text):
                raise ValueError(
                    f"slide {self.id!r} {field_name} contains "
                    "generic launch-copy filler"
                )
        if len(self.headline.split()) > _MAX_HEADLINE_WORDS:
            raise ValueError(
                f"slide {self.id!r} headline exceeds {_MAX_HEADLINE_WORDS} words"
            )
        if len(self.visible_text.split()) > _MAX_VISIBLE_WORDS:
            raise ValueError(
                f"slide {self.id!r} visible_text exceeds {_MAX_VISIBLE_WORDS} words"
            )
        for source in self.sources:
            if source not in _SOURCE_ENUM:
                raise ValueError(f"slide {self.id!r} has invalid source {source!r}")
        # Substance floor (P3.4): a product/walkthrough/trust slide must carry a
        # real points/metric descriptor, not a decorative swatch. Enforced on
        # fresh generations; grandfathered for spliced/legacy payloads (section
        # regeneration carries over acts authored before this floor) via the same
        # ``GRANDFATHER_NOTE_DEPTH`` context flag that grandfathers note depth.
        if not (info.context or {}).get(GRANDFATHER_NOTE_DEPTH):
            if self.type in _SUBSTANCE_SLIDE_TYPES and not visual_has_substance(
                self.visual
            ):
                raise ValueError(
                    f"slide {self.id!r} of type {self.type!r} must carry a non-empty "
                    "'points' array or a metric/value descriptor"
                )
        return self


class StoryboardDiagramLayer(BaseModel):
    """One plane of an architecture diagram, each backed by source refs."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=_ID_PATTERN)
    kind: str = Field(
        pattern=r"^(client|frontend|api|data|llm|integrations|trust|recovery|group)$"
    )
    label: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=400)
    source_refs: list[SourceRef] = Field(min_length=1)


class StoryboardDiagram(BaseModel):
    """A diagram. The ``architecture_reveal`` diagram has stricter layer rules."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=_ID_PATTERN)
    type: str = Field(min_length=1)
    layers: list[StoryboardDiagramLayer] = Field(min_length=1)

    @model_validator(mode="after")
    def _architecture_reveal_layers(self) -> "StoryboardDiagram":
        # storyboard-v1.5: only the three core planes are required. Optional planes
        # (frontend/llm/integrations/trust/recovery) are allowed but not mandated,
        # so a product without them is not forced to invent them. Legacy 8-layer
        # decks still validate (8 ⊇ core), so no grandfathering is needed.
        if self.type == ARCHITECTURE_REVEAL_TYPE:
            kinds = {layer.kind for layer in self.layers}
            missing = [k for k in CORE_ARCHITECTURE_LAYERS if k not in kinds]
            if missing:
                raise ValueError(
                    "architecture_reveal diagram is missing required core layers: "
                    + ", ".join(missing)
                )
        return self


class StoryboardTheme(BaseModel):
    """Visual identity: palette, typography mood, motif, transitions, diagrams."""

    model_config = ConfigDict(extra="forbid")

    palette: list[str] = Field(min_length=3, max_length=8)
    typography: str = Field(min_length=1)
    motif: str = Field(min_length=1)
    transition_style: str = Field(min_length=1)
    diagram_style: str = Field(min_length=1)

    @model_validator(mode="after")
    def _palette_is_hex(self) -> "StoryboardTheme":
        hex_re = re.compile(r"^#[0-9A-Fa-f]{6}$")
        for colour in self.palette:
            if not hex_re.match(colour):
                raise ValueError(f"palette colour {colour!r} must be a #RRGGBB hex")
        return self


class StoryboardSection(BaseModel):
    """One top-level act. Title must be one of the six fixed acts."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=_ID_PATTERN)
    title: str = Field(min_length=1)
    slides: list[StoryboardSlide] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Root payload
# ---------------------------------------------------------------------------


class StoryboardPayload(BaseModel):
    """The complete structured keynote the LLM returns.

    Kept aligned with ``harness/schemas/storyboard-payload.schema.json``. Stricter
    where the directive demands it (the three core architecture layers; the six
    exact act titles), so any payload this model accepts also satisfies the JSON
    schema.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    theme: StoryboardTheme
    sections: list[StoryboardSection] = Field(min_length=6, max_length=6)
    diagrams: list[StoryboardDiagram] = Field(min_length=1)
    source_map: dict[str, list[SourceRef]] = Field(min_length=1)
    notes: dict[str, SpeakerNote] = Field(min_length=1)
    demo_script_md: str = Field(min_length=1)
    technical_appendix_md: str = Field(min_length=1)

    @model_validator(mode="after")
    def _enforce_acts_and_architecture(self) -> "StoryboardPayload":
        if self.title.strip().lower() in _GENERIC_TITLES:
            raise ValueError(
                "title must name the actual product or workspace, not a generic keynote"
            )
        if _FORBIDDEN_VIDEO_DEMO_RE.search(self.demo_script_md):
            raise ValueError("demo_script_md must not request or describe a video demo")

        titles = [section.title for section in self.sections]

        forbidden = [t for t in titles if t in FORBIDDEN_TOP_LEVEL_ACTS]
        if forbidden:
            raise ValueError(
                "Validation and Execution Plan are not top-level acts; found: "
                + ", ".join(forbidden)
            )
        if tuple(titles) != REQUIRED_SECTION_TITLES:
            raise ValueError(
                "sections must be exactly the six acts in order "
                f"{list(REQUIRED_SECTION_TITLES)}, got {titles}"
            )

        reveals = [d for d in self.diagrams if d.type == ARCHITECTURE_REVEAL_TYPE]
        if not reveals:
            raise ValueError("at least one architecture_reveal diagram is required")

        for values in self.source_map.values():
            if not values:
                raise ValueError("every source_map entry must cite at least one source")
        note_keys = set(self.notes)
        for section in self.sections:
            for slide in section.slides:
                if (
                    slide.speaker_notes_ref not in note_keys
                    and slide.id not in note_keys
                ):
                    raise ValueError(
                        f"slide {slide.id!r} is missing a matching speaker note"
                    )
        return self


# ---------------------------------------------------------------------------
# Prompt construction (local / in-code; never loaded from Langfuse in V1)
# ---------------------------------------------------------------------------

_ACTS_BLOCK = "\n".join(
    f"  {i + 1}. {t}" for i, t in enumerate(REQUIRED_SECTION_TITLES)
)
_LAYERS_BLOCK = ", ".join(ARCHITECTURE_LAYER_KINDS)
_CORE_LAYERS_BLOCK = ", ".join(CORE_ARCHITECTURE_LAYERS)
_OPTIONAL_LAYERS_BLOCK = ", ".join(OPTIONAL_ARCHITECTURE_LAYERS)
_VISUAL_KINDS_BLOCK = ", ".join(ALLOWED_VISUAL_KINDS)
_CANONICAL_KEYS_BLOCK = """CANONICAL JSON SHAPE — use these keys exactly.
Root object keys:
  title, theme, sections, diagrams, source_map, notes, demo_script_md,
  technical_appendix_md
theme keys:
  palette, typography, motif, transition_style, diagram_style
section keys:
  id, title, slides
slide keys:
  id, type, headline, visible_text, visual, speaker_notes_ref, sources
  sources is an array of source enum strings only, for example ["SPEC", "PLAN"].
  It is not an array of objects.
visual keys:
  kind plus optional inert descriptor keys
  kind must be a renderer-supported layout, never a media promise.
diagram keys:
  id, type, layers
diagram layer keys:
  id, kind, label, summary, source_refs
source reference keys:
  source, source_id, excerpt
  source references are objects used in source_map and diagram layer source_refs.
  Never add url, link, href, title, or heading fields to a source reference.
speaker note keys:
  slide_id, talk_track, transition, timing_seconds, pause_cue, demo_cue,
  backup_points

Do not use alias keys. In particular, never use colour_palette,
typography_mood, text, note_ref, speaker_note_ref, speakerNotesRef, sourceRefs,
sourceMap, demo_script, or technical_appendix. If you need slide body text, the
key is visible_text. If you need theme colours, the key is palette."""
_MINIMAL_PAYLOAD_SHAPE = """FIELD SHAPE EXAMPLE — expand this structure to six
sections and the architecture layers your product actually has (the three core
planes plus any optional planes the sources describe), but do not rename keys:
{
  "title": "SpecForge Launch Keynote",
  "theme": {
    "palette": ["#0B1020", "#6D28D9", "#1FB6FF", "#F5A623", "#10B981", "#EC4899"],
    "typography": "Modern geometric sans",
    "motif": "Layered product glass",
    "transition_style": "Cinematic fades",
    "diagram_style": "Layered architecture planes"
  },
  "sections": [
    {
      "id": "act-1",
      "title": "Opening Thesis",
      "slides": [
        {
          "id": "slide-1",
          "type": "thesis",
          "headline": "One concise headline",
          "visible_text": "One sparse visible line.",
          "visual": {
            "kind": "bullets",
            "points": [
              "Concrete sourced point",
              "Second sourced point",
              "Third sourced point"
            ]
          },
          "speaker_notes_ref": "slide-1",
          "sources": ["SPEC", "PLAN"]
        }
      ]
    }
  ],
  "diagrams": [
    {
      "id": "architecture-reveal",
      "type": "architecture_reveal",
      "layers": [
        {
          "id": "layer-api",
          "kind": "api",
          "label": "API layer",
          "summary": "Short sourced summary.",
          "source_refs": [
            {
              "source": "PLAN",
              "source_id": "PLAN:architecture",
              "excerpt": "Bounded source excerpt."
            }
          ]
        }
      ]
    }
  ],
  "source_map": {
    "claim-1": [
      {
        "source": "SPEC",
        "source_id": "SPEC:overview",
        "excerpt": "Bounded source excerpt."
      }
    ]
  },
  "notes": {
    "slide-1": {
      "slide_id": "slide-1",
      "talk_track": "A rich, source-grounded 4-6 sentence presenter script.",
      "transition": "A one-to-two sentence bridge into the next slide.",
      "timing_seconds": 45,
      "pause_cue": "Pause for emphasis.",
      "demo_cue": "",
      "backup_points": [
        "First source-backed Q&A point.",
        "Second source-backed Q&A point."
      ]
    }
  },
  "demo_script_md": "## Demo\\n1. Show the product workflow.",
  "technical_appendix_md": "## Appendix\\nArchitecture backup."
}

The final architecture_reveal layers array must include at least the three
required core kinds — client, api, data — plus any of the optional kinds
(frontend, llm, integrations, trust, recovery) the product actually has. Use
these exact kind values; never rename them, and never fabricate an optional
plane the sources do not describe. Omitting an absent plane is correct."""

SYSTEM_PROMPT = f"""You are SpecForge's Storyboard keynote director. Turn a finalised
SPEC + PLAN + HARNESS + TASKS into a polished, product-specific launch keynote — never a
generic deck. Ground every claim in the provided sources; never invent capabilities,
metrics, pricing, commercial claims, timelines, customer promises, or components.

OUTPUT CONTRACT — return one strict JSON object only: no prose, no Markdown fences, no
commentary. It must match the Storyboard payload schema.

{_CANONICAL_KEYS_BLOCK}

{_MINIMAL_PAYLOAD_SHAPE}

THE SIX TOP-LEVEL ACTS — exactly six sections, these exact titles in order:
{_ACTS_BLOCK}
Validation and Execution Plan are NOT top-level acts — never title a section "Validation"
or "Execution Plan"; that material lives in the technical appendix, demo script, or Q&A
backup, never on the main deck.

ARCHITECTURE REVEAL — include at least one diagram of type "architecture_reveal". Always
include the three core planes: {_CORE_LAYERS_BLOCK} — an actor/client, the compute/API, and
the data/state store; every product has them. Include an optional plane ({_OPTIONAL_LAYERS_BLOCK})
ONLY when the SPEC/PLAN actually describes such a component: omitting an absent plane is correct,
fabricating one is a failure. A CLI, batch job, or library with no browser UI omits "frontend"; a
product that makes no model calls omits "llm"; one with no third-party services omits
"integrations". The valid layer kinds are: {_LAYERS_BLOCK}. Each layer needs a label that names the
REAL components from the sources (e.g. "FastAPI + arq worker", never a bare "API layer") and at
least one source reference to PLAN/HARNESS/SPEC/TASKS. Prioritise PLAN architecture, security
architecture, capacity model, STRIDE, SLO, and FMEA evidence for the Technical Architecture and
Trust, Security, Reliability acts.

VISUALS — visual.kind must be one of these renderer-supported layouts: {_VISUAL_KINDS_BLOCK}.
Never output "illustration", "video-demo", "video", "infographic", "call-to-action", "image",
"photo", "screenshot", or anything implying a generated asset or media file — the trusted
renderer draws visuals from structured data. Make each visual carry real content: for
bullets/product/walkthrough/trust/thesis/closing slides add a "points" array of 3–5 short,
concrete, source-backed phrases (≤ 8 words each — a capability, guarantee, step, or layer;
never a sentence or marketing copy); for metric slides add "value" (a source-backed figure,
e.g. "4 pipeline stages" or "80% coverage gate") and a "label" naming what it measures (only
numbers that appear in the sources). Descriptors are drawn as the visual, not extra body
text, and obey the same grounding/no-filler rules.

SLIDE RULES — one idea per slide. Aim for 12–18 slides total, 2–3 per act (Opening Thesis and
Launch Close may run 1–2). Headlines ≤ 18 words and must add a distinct angle — never simply
restate the slide's visible_text. Visible slide text stays sparse: ≤ 45 visible words per slide
unless diagram labels require more. Every product, walkthrough, and trust slide must carry real
substance in its visual — a "points" array of 3–5 concrete source-backed phrases or a "metric"
value/label — never a bare decorative visual. Depth lives in speaker notes, visual descriptors,
and the technical appendix — not in long slide paragraphs.

SPEAKER NOTES — where the depth lives; make every note substantial. One note per slide, keyed
by slide id. Each talk_track is a rich ~4–6 sentence (≈ 80–160 word) presenter script: open
with the slide's point, name the concrete product detail or architecture component from the
sources, explain why it matters, land the takeaway — all grounded, never generic. transition
is a real 1–2 sentence bridge to the next slide; set realistic timing_seconds; pause_cue names
the exact moment to pause; provide at least two backup_points per slide for Q&A, each a concrete
source-backed fact a presenter can deploy under questioning. Add a live walkthrough cue in
demo_cue when the sources support one, otherwise leave demo_cue an empty string. Never mention
or request a video demo.

WALKTHROUGH SCRIPT — keep the API field name demo_script_md; its Markdown is a source-backed
live walkthrough script mapping concrete product actions to specific slides so a presenter
drives the product in the browser. Not a video demo, recording script, or asset request.

TECHNICAL APPENDIX — technical_appendix_md (Markdown) carries architecture, security,
reliability, testing, task, and Q&A backup depth, separate from the main deck.

SOURCE MAP — map every major claim and architecture component to bounded finalised source
excerpts. Cite only the source ids you were given, exactly as written ("SPEC:overview", not
"SPEC"); never fabricate or paraphrase a citation id. Key source_map entries by slide id. Each
excerpt is a SHORT supporting quote or tight paraphrase of the named source section — ≤ 300
characters, never a wall of copied text. Grounding is proven by the source id, not by copying
long passages.

VISUAL IDENTITY — provide a theme distinctive to THIS product, not a house style. The renderer
drives the cover gradient, per-act accent rotation, slide accents, and visual cards from your
palette, so provide 5–8 #RRGGBB hex values with real range (a deep anchor colour, two or three
vivid domain-fitting accents, a brighter highlight) so the six acts each take a visibly
different accent — never a flat, near-monochrome palette. Also give a typography mood, a motif
(short evocative phrase), a transition style, and a diagram style.

RENDERING SAFETY — you produce structured content only. NEVER emit HTML, CSS, JavaScript, a
<script> tag or any generated script, inline event handlers, iframes, object/embed tags,
external or third-party fonts, remote assets, remote image or stylesheet URLs, or tracking
pixels. Rendering is owned by trusted application code; any markup, styling, or executable
instruction you emit is treated as hostile text and discarded.

{SECURITY_AND_PRIVACY_RULES}"""


def _render_sources_block(source: StoryboardSourcePackage) -> str:
    lines: list[str] = []
    for source_id, excerpt in source.excerpts.items():
        body = wrap_untrusted_content(source_id, excerpt.excerpt)
        lines.append(f"### {source_id} (heading: {excerpt.heading})\n{body}")
    if source.missing_source_sections:
        missing = ", ".join(m.source_id for m in source.missing_source_sections)
        lines.append(
            "### unavailable sources\n"
            "These expected sections were not present and MUST NOT be "
            f"invented: {missing}"
        )
    return "\n\n".join(lines)


def _render_source_ids_block(source: StoryboardSourcePackage) -> str:
    lines: list[str] = []
    for source_id, excerpt in source.excerpts.items():
        lines.append(f"- {source_id} (source: {excerpt.stage.upper()})")
    return "\n".join(lines) or "- none"


def _source_product_name(source: StoryboardSourcePackage) -> str:
    """Prefer the SPEC title when the workspace name is only a placeholder."""

    workspace_name = source.workspace_name.strip()
    spec_title = ""
    match = _TITLE_RE.search(source.artifacts.get("spec", ""))
    if match:
        spec_title = match.group(1).strip()
    if spec_title and (
        not workspace_name or _PLACEHOLDER_WORKSPACE_RE.match(workspace_name)
    ):
        return spec_title
    return workspace_name or spec_title or "Storyboard"


def build_user_prompt(source: StoryboardSourcePackage) -> str:
    """Render the user prompt grounding the keynote in the finalised sources.

    The workspace problem statement and every source excerpt are wrapped as
    untrusted content so injection attempts inside finalised artifacts cannot
    redirect the keynote director.
    """

    problem = wrap_untrusted_content("problem_statement", source.problem_statement)
    sources_block = _render_sources_block(source)
    source_ids_block = _render_source_ids_block(source)
    product_name = _source_product_name(source)
    return f"""Build the launch keynote for this product. Ground every claim, metric, and
architecture component in the finalised sources below. Produce the strict JSON payload
described in the system prompt.

PRODUCT NAME: {product_name}
WORKSPACE NAME: {source.workspace_name}

PROBLEM STATEMENT:
{problem}

AVAILABLE SOURCE IDS — every source_map and diagram source_refs entry must use one of these
exact source_id values and the matching source enum:
{source_ids_block}

FINALISED SOURCE EXCERPTS (cite these source ids in your source_map):
{sources_block}

Quality bar: title, headlines, notes, and walkthrough describe this specific product from the
sources. Do not use "Product Launch Keynote" or generic launch-copy filler ("empower your
business", "join the revolution", "operational excellence", "transform your...", "game
changing"). Do not invent pricing, customer promises, real-time capabilities, or any
video-demo asset.

SOURCE MAP — key source_map entries by slide id; every slide id needs at least one entry (the
exact slide id or a key prefixed "<slide_id>."). Each source_map and diagram source_refs excerpt
is a SHORT supporting quote or tight paraphrase of the matching source section above — keep each
to ≤ 300 characters; do not copy long passages verbatim.

Return only the JSON Storyboard payload."""


def build_repair_user_prompt(previous_output: str, errors: str) -> str:
    """Build the single repair prompt sent after a parse/validation failure.

    Carries the validation errors (field locations and messages only — never the
    raw account/source data) plus the previous output so the model can correct it.
    """

    wrapped = wrap_untrusted_content("previous_invalid_output", previous_output)
    return f"""Your previous response was not a valid Storyboard payload. Fix it.

VALIDATION ERRORS:
{errors}

{_CANONICAL_KEYS_BLOCK}

{_MINIMAL_PAYLOAD_SHAPE}

Return a corrected strict JSON Storyboard payload that resolves every error
above and still satisfies all system-prompt rules (exactly six acts with the
required titles, the architecture_reveal layers, sparse slides, speaker notes,
demo script, technical appendix, source map, and visual identity). Output only
the JSON object — no prose, no Markdown fences.

PREVIOUS OUTPUT:
{wrapped}"""


# ---------------------------------------------------------------------------
# Parse / validate with one internal repair attempt
# ---------------------------------------------------------------------------


class StoryboardPayloadError(Exception):
    """Raised when generated output cannot be parsed/validated into a payload.

    ``stage`` is ``"parse"`` (invalid JSON) or ``"schema"`` (failed validation).
    ``summary`` is a redaction-safe description (field locations + messages, never
    raw input values) suitable for the repair prompt and for T-254 to record as
    the failure reason. The raw payload is never carried here or logged.
    """

    def __init__(self, stage: str, summary: str) -> None:
        self.stage = stage
        self.summary = summary
        super().__init__(f"storyboard payload {stage} error: {summary}")


# Repair is injected by T-254 so this module stays free of LLM wiring and remains
# unit-testable: it takes the repair user prompt and returns the model's raw text.
StoryboardRepairFn = Callable[[str], Awaitable[str]]


def _strip_code_fences(raw: str) -> str:
    """Strip a wrapping Markdown code fence (```lang … ```), if present."""

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()
    return text


def _extract_json_object(raw: str) -> str:
    """Strip Markdown fences and slice to the outer brace pair."""

    text = _strip_code_fences(raw)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def looks_truncated(raw: str) -> bool:
    """Whether *raw* is a *truncated* JSON payload, not a complete-but-invalid one.

    The dominant parse-failure mode for a large keynote payload is the model
    hitting its output-token ceiling mid-object. The signature is two-part and
    deliberately conservative: the payload fails to parse as JSON **and**, once
    Markdown fences are stripped, it does not end on a closing brace (a complete
    object always does, even a schema-invalid one). A complete payload that merely
    fails schema validation parses cleanly here and returns ``False`` — so it
    flows to the normal repair loop instead of a wasteful budget-doubling retry —
    and so does complete-but-malformed JSON that still ends in ``}`` (a genuine
    syntax error the repair prompt can fix under the same budget). This is the
    gate the service uses to decide the one-shot doubled-budget retry (P3.3).
    """

    try:
        json.loads(_extract_json_object(raw))
    except json.JSONDecodeError:
        return not _strip_code_fences(raw).rstrip().endswith("}")
    return False


def _summarise_validation_error(exc: Exception) -> str:
    """Build a redaction-safe error summary (locations + messages, no inputs)."""

    errors = getattr(exc, "errors", None)
    if callable(errors):
        parts: list[str] = []
        for err in exc.errors():  # type: ignore[attr-defined]
            loc = ".".join(str(p) for p in err.get("loc", ()))
            parts.append(
                f"{loc or '<root>'}: {err.get('msg', '')} [{err.get('type', '')}]"
            )
        if parts:
            return "; ".join(parts[:25])
    return type(exc).__name__


def _validate(raw: str) -> StoryboardPayload:
    """Parse JSON and validate into a ``StoryboardPayload`` or raise typed error."""

    try:
        data = json.loads(_extract_json_object(raw))
    except json.JSONDecodeError as exc:
        raise StoryboardPayloadError(
            "parse", f"invalid JSON at line {exc.lineno}"
        ) from exc

    try:
        return StoryboardPayload.model_validate(data)
    except Exception as exc:  # pydantic ValidationError (and any validator ValueError)
        raise StoryboardPayloadError(
            "schema", _summarise_validation_error(exc)
        ) from exc


async def parse_and_validate_payload(
    raw: str,
    *,
    repair: StoryboardRepairFn | None = None,
) -> StoryboardPayload:
    """Validate generated output, allowing exactly one internal repair attempt.

    On the first parse/validation failure, if a ``repair`` callable is supplied we
    invoke it once with a repair prompt built from the redaction-safe error
    summary, then validate the repaired output. A second failure raises
    ``StoryboardPayloadError`` for T-254 to mark the Storyboard failed and refund.
    There is no second repair loop.
    """

    try:
        return _validate(raw)
    except StoryboardPayloadError as first_error:
        if repair is None:
            raise
        repair_prompt = build_repair_user_prompt(raw, first_error.summary)
        repaired = await repair(repair_prompt)
        # One attempt only — a failure here propagates as the typed error.
        return _validate(repaired)

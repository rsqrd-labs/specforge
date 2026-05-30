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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prompts.base import SECURITY_AND_PRIVACY_RULES, wrap_untrusted_content
from services.pipeline.storyboard_source import StoryboardSourcePackage

STORYBOARD_PROMPT_VERSION = "storyboard-v1.3"

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
# Every architecture reveal must layer these eight planes so the diagram tells a
# complete system story (client through recovery).
REQUIRED_ARCHITECTURE_LAYERS: tuple[str, ...] = (
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

_ID_PATTERN = r"^[a-z0-9-]+$"
_MAX_EXCERPT_CHARS = 1200
_MAX_HEADLINE_WORDS = 18
_MAX_VISIBLE_WORDS = 45
_FORBIDDEN_VIDEO_DEMO_RE = re.compile(
    r"\b(video|recorded|recording)\s+(demo|demonstration|walkthrough)\b|"
    r"\b(demo|demonstration|walkthrough)\s+video\b",
    re.IGNORECASE,
)
_GENERIC_TITLES = {
    "product launch keynote",
    "launch keynote",
    "product keynote",
    "storyboard keynote",
    "product launch deck",
}


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
    def _validate_notes(self) -> "SpeakerNote":
        if _FORBIDDEN_VIDEO_DEMO_RE.search(self.demo_cue):
            raise ValueError("demo_cue must not request or describe a video demo")
        for point in self.backup_points:
            if not point.strip():
                raise ValueError("backup_points entries must be non-empty")
            if _FORBIDDEN_VIDEO_DEMO_RE.search(point):
                raise ValueError("backup_points must not request a video demo")
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
    def _enforce_sparse_and_sources(self) -> "StoryboardSlide":
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
        if self.type == ARCHITECTURE_REVEAL_TYPE:
            kinds = {layer.kind for layer in self.layers}
            missing = [k for k in REQUIRED_ARCHITECTURE_LAYERS if k not in kinds]
            if missing:
                raise ValueError(
                    "architecture_reveal diagram is missing required layers: "
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
        import re

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
    where the directive demands it (all eight architecture layers; the six exact
    act titles), so any payload this model accepts also satisfies the JSON schema.
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
_LAYERS_BLOCK = ", ".join(REQUIRED_ARCHITECTURE_LAYERS)
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
sections and all eight architecture layers, but do not rename keys:
{
  "title": "SpecForge Launch Keynote",
  "theme": {
    "palette": ["#101418", "#1FB6FF", "#F5A623"],
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
          "visual": {"kind": "hero"},
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
      "talk_track": "Presenter talk track.",
      "transition": "Transition to next slide.",
      "timing_seconds": 45,
      "pause_cue": "Pause for emphasis.",
      "demo_cue": "",
      "backup_points": ["One Q&A backup point."]
    }
  },
  "demo_script_md": "## Demo\\n1. Show the product workflow.",
  "technical_appendix_md": "## Appendix\\nArchitecture backup."
}

The final architecture_reveal layers array must include at least one layer
object for each required kind, using these exact kind values:
client, frontend, api, data, llm, integrations, trust, recovery.
Do not combine, rename, or omit any of those eight architecture layer kinds."""

SYSTEM_PROMPT = f"""You are SpecForge's Storyboard keynote director. You turn a
finalised SPEC + PLAN + HARNESS + TASKS into a polished, product-specific launch
keynote — not a generic slide deck. Every claim is grounded in the provided
finalised sources; you never invent capabilities, metrics, pricing, commercial
claims, timelines, customer promises, or components.

OUTPUT CONTRACT — return one strict JSON object only. No prose, no Markdown
fences, no commentary. The object must match the Storyboard payload schema.

{_CANONICAL_KEYS_BLOCK}

{_MINIMAL_PAYLOAD_SHAPE}

THE SIX TOP-LEVEL ACTS — exactly six sections, with these exact titles, in order:
{_ACTS_BLOCK}

Validation and Execution Plan are NOT top-level acts. Never create a top-level
section titled "Validation" or "Execution Plan"; that material belongs in the
technical appendix, demo script, or Q&A backup, never on the main deck.

ARCHITECTURE REVEAL — include at least one diagram of type "architecture_reveal"
whose layers cover all of these planes: {_LAYERS_BLOCK}. Each layer needs a label
and at least one source reference back to PLAN/HARNESS/SPEC/TASKS. Prioritise PLAN
architecture, security architecture, capacity model, STRIDE, SLO, and FMEA
evidence for the Technical Architecture act and the Trust, Security, Reliability
act.

VISUALS — visual.kind must be one of these exact renderer-supported layouts:
{_VISUAL_KINDS_BLOCK}. Never output "illustration", "video-demo", "video",
"infographic", "call-to-action", "image", "photo", "screenshot", or any visual
that implies a generated asset or media file. The trusted renderer draws the
visuals from structured data.

SLIDE RULES — one idea per slide. Headlines are at most 18 words. Visible slide
text stays sparse: at most 45 visible words per slide unless diagram labels
require more. The main deck stays sparse; depth lives in speaker notes and the
technical appendix, not on the slides.

SPEAKER NOTES — provide one note per slide keyed by the slide id, each with a
talk track, a transition, timing (seconds), a pause cue, a concise live
walkthrough cue when the sources support one, and backup points for Q&A. Leave
demo_cue as an empty string when there is no source-backed live action. Never
mention or request a video demo.

WALKTHROUGH SCRIPT — keep the API field name demo_script_md, but its Markdown
content is a source-backed live walkthrough script. It maps concrete product
actions to specific slides so a presenter can drive the product in the browser.
It is not a video demo, recording script, or asset request.

TECHNICAL APPENDIX — the technical appendix (Markdown) carries architecture,
security, reliability, testing, task, and Q&A backup depth. It is separate from
the main deck.

SOURCE MAP — provide a source map so every major claim and every architecture
component maps to bounded finalised source excerpts. Only cite the source ids you
were given, exactly as written, such as "SPEC:overview" rather than "SPEC";
never fabricate or paraphrase a citation id.

VISUAL IDENTITY — provide a theme expressing the product's visual identity: a
colour palette (3-8 #RRGGBB hex values), a typography mood, a motif, a transition
style, and a diagram style.

RENDERING SAFETY — you produce structured content only. NEVER emit HTML, CSS,
JavaScript, a <script> tag or any generated script, inline event handlers,
iframes, object/embed tags, external or third-party fonts, remote assets, remote
image or stylesheet URLs, or tracking pixels. Rendering is owned by trusted
application code; any markup, styling, or executable instruction you emit will be
treated as hostile text and discarded.

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


def build_user_prompt(source: StoryboardSourcePackage) -> str:
    """Render the user prompt grounding the keynote in the finalised sources.

    The workspace problem statement and every source excerpt are wrapped as
    untrusted content so injection attempts inside finalised artifacts cannot
    redirect the keynote director.
    """

    problem = wrap_untrusted_content("problem_statement", source.problem_statement)
    sources_block = _render_sources_block(source)
    source_ids_block = _render_source_ids_block(source)
    return f"""Build the launch keynote for this product. Ground every claim,
metric, and architecture component in the finalised sources below. Produce the
strict JSON payload described in the system prompt.

PRODUCT NAME: {source.workspace_name}

PROBLEM STATEMENT:
{problem}

AVAILABLE SOURCE IDS — every source_map and diagram source_refs entry must use
one of these exact source_id values and the matching source enum:
{source_ids_block}

FINALISED SOURCE EXCERPTS (cite these source ids in your source_map):
{sources_block}

Quality bar: the title, headlines, notes, and walkthrough must describe this
specific product from the sources. Do not use "Product Launch Keynote" or other
generic launch-copy filler. Do not invent pricing, customer promises, real-time
capabilities, or any video-demo asset.

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


def _extract_json_object(raw: str) -> str:
    """Strip Markdown fences and slice to the outer brace pair."""

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


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

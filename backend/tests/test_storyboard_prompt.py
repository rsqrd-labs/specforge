"""Unit tests for the Storyboard prompt + payload schema (Phase 20 — T-253).

Covers the strict payload schema (six exact acts, Validation/Execution Plan
rejection, architecture-reveal layer enforcement, sparse-slide rules), the
one-internal-repair parse flow, and parity with the harness JSON schema.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from prompts.storyboard import (
    ALLOWED_VISUAL_KINDS,
    ARCHITECTURE_LAYER_KINDS,
    CORE_ARCHITECTURE_LAYERS,
    GRANDFATHER_NOTE_DEPTH,
    OPTIONAL_ARCHITECTURE_LAYERS,
    REQUIRED_SECTION_TITLES,
    STORYBOARD_PROMPT_VERSION,
    SYSTEM_PROMPT,
    StoryboardPayload,
    StoryboardPayloadError,
    build_repair_user_prompt,
    build_user_prompt,
    looks_truncated,
    parse_and_validate_payload,
)
from services.pipeline.storyboard_source import (
    SourceExcerpt,
    StoryboardSourcePackage,
)

_HARNESS_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "harness"
    / "schemas"
    / "storyboard-payload.schema.json"
)


# ---------------------------------------------------------------------------
# A schema-valid payload we can mutate per test
# ---------------------------------------------------------------------------


def _source_ref(source: str = "PLAN") -> dict[str, Any]:
    return {"source": source, "source_id": f"{source}:architecture", "excerpt": "x"}


def _slide(slide_id: str, slide_type: str) -> dict[str, Any]:
    return {
        "id": slide_id,
        "type": slide_type,
        "headline": "A crisp headline",
        "visible_text": "Sparse supporting line.",
        # Carry a substance descriptor so product/walkthrough/trust slides clear
        # the P3.4 fresh-generation substance floor by default; tests that want to
        # exercise the floor drop it explicitly.
        "visual": {
            "kind": "bullets",
            "points": ["Grounded point one", "Grounded point two", "Third point"],
        },
        "speaker_notes_ref": slide_id,
        "sources": ["PLAN"],
    }


def _note(slide_id: str) -> dict[str, Any]:
    return {
        "slide_id": slide_id,
        "talk_track": (
            "Say this clearly and with intent. Open on the slide's single point, "
            "name the specific product detail drawn from the finalised sources, "
            "explain why it matters to the audience, and close on the takeaway."
        ),
        "transition": "Then move on.",
        "timing_seconds": 30,
        "pause_cue": "Pause here.",
        "demo_cue": "",
        "backup_points": ["A backup point", "A second backup point"],
    }


def _arch_layers(kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"layer-{kind}",
            "kind": kind,
            "label": f"{kind} layer",
            "summary": "",
            "source_refs": [_source_ref()],
        }
        for kind in kinds
    ]


def _architecture_reveal(
    kinds: tuple[str, ...] = ARCHITECTURE_LAYER_KINDS,
) -> dict[str, Any]:
    return {
        "id": "arch-reveal",
        "type": "architecture_reveal",
        "layers": _arch_layers(kinds),
    }


def _valid_payload() -> dict[str, Any]:
    section_types = [
        "thesis",
        "product",
        "walkthrough",
        "architecture",
        "trust",
        "closing",
    ]
    sections = []
    for idx, title in enumerate(REQUIRED_SECTION_TITLES):
        slide_id = f"s{idx}"
        sections.append(
            {
                "id": f"act-{idx}",
                "title": title,
                "slides": [_slide(slide_id, section_types[idx])],
            }
        )
    notes = {f"s{idx}": _note(f"s{idx}") for idx in range(6)}
    return {
        "title": "Thought2Build Launch Keynote",
        "theme": {
            # 5 colours: fresh generations must meet the prompt's 5–8 palette
            # floor (audit L16); only grandfathered legacy payloads may carry 3.
            "palette": ["#101010", "#2244FF", "#FFAA00", "#F5F5F5", "#22CC88"],
            "typography": "Modern geometric sans",
            "motif": "Glass panels",
            "transition_style": "Smooth fades",
            "diagram_style": "Layered isometric",
        },
        "sections": sections,
        "diagrams": [_architecture_reveal()],
        "source_map": {"s0": [_source_ref("SPEC")]},
        "notes": notes,
        "demo_script_md": "# Demo\n1. Click generate on slide s1.",
        "technical_appendix_md": (
            "# Appendix\nArchitecture, security, reliability, Q&A."
        ),
    }


def test_valid_payload_validates() -> None:
    payload = StoryboardPayload.model_validate(_valid_payload())
    assert [s.title for s in payload.sections] == list(REQUIRED_SECTION_TITLES)


def test_note_depth_floor_enforced_on_fresh_generation() -> None:
    data = _valid_payload()
    # A stub note: short talk track and a single backup point.
    data["notes"]["s0"]["talk_track"] = "Too short."
    data["notes"]["s0"]["backup_points"] = ["only one"]
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    message = str(exc.value).lower()
    assert "talk_track" in message or "backup_points" in message


def test_note_depth_floor_grandfathered_for_carried_over_notes() -> None:
    # Section regeneration re-validates the whole spliced payload, which may carry
    # pre-v1.4 short notes from untouched acts. The grandfather context must let
    # those through so tightening the floor never breaks regen on existing decks.
    data = _valid_payload()
    data["notes"]["s0"]["talk_track"] = "Too short."
    data["notes"]["s0"]["backup_points"] = ["only one"]
    payload = StoryboardPayload.model_validate(
        data, context={GRANDFATHER_NOTE_DEPTH: True}
    )
    assert payload.notes["s0"].talk_track == "Too short."


# ---------------------------------------------------------------------------
# P3.4 — slide substance floor (product / walkthrough / trust)
# ---------------------------------------------------------------------------


def test_slide_substance_floor_enforced_on_fresh_generation() -> None:
    # A product-type slide with a bare decorative visual (no points, no metric)
    # must fail the fresh-generation substance floor. Section index 1 (Product
    # Vision) carries a "product"-type slide in _valid_payload.
    data = _valid_payload()
    data["sections"][1]["slides"][0]["visual"] = {"kind": "bullets"}
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    message = str(exc.value).lower()
    assert "points" in message or "metric" in message


def test_slide_substance_floor_grandfathered_for_spliced_payload() -> None:
    # The same bare visual passes under the grandfather context section
    # regeneration uses to re-validate a spliced payload carrying legacy acts.
    data = _valid_payload()
    data["sections"][1]["slides"][0]["visual"] = {"kind": "bullets"}
    payload = StoryboardPayload.model_validate(
        data, context={GRANDFATHER_NOTE_DEPTH: True}
    )
    assert payload.sections[1].slides[0].visual.kind == "bullets"


# ---------------------------------------------------------------------------
# Audit L16 — palette floor: prompt demands 5–8, schema must agree for fresh
# generations (a prompt-violating payload validating cleanly means the repair
# pass that exists exactly for schema misses never fires).
# ---------------------------------------------------------------------------


def test_palette_floor_enforced_on_fresh_generation() -> None:
    data = _valid_payload()
    data["theme"]["palette"] = ["#101010", "#2244FF", "#FFAA00"]
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "at least 5 colours" in str(exc.value)


def test_palette_floor_grandfathered_for_legacy_payload() -> None:
    # Stored pre-L16 decks (3–4 colours) re-validate during section regen under
    # the same grandfather context that relaxes note depth — tightening the
    # floor must never break existing decks.
    data = _valid_payload()
    data["theme"]["palette"] = ["#101010", "#2244FF", "#FFAA00"]
    payload = StoryboardPayload.model_validate(
        data, context={GRANDFATHER_NOTE_DEPTH: True}
    )
    assert len(payload.theme.palette) == 3


def test_palette_structural_floor_still_three_when_grandfathered() -> None:
    # The structural minimum stays 3 — fewer than 3 fails even grandfathered.
    data = _valid_payload()
    data["theme"]["palette"] = ["#101010", "#2244FF"]
    with pytest.raises(Exception):
        StoryboardPayload.model_validate(data, context={GRANDFATHER_NOTE_DEPTH: True})


def test_palette_hex_check_runs_before_floor() -> None:
    # A malformed colour is reported as the hex error even when the count is
    # also under the fresh floor.
    data = _valid_payload()
    data["theme"]["palette"] = ["red", "#2244FF", "#FFAA00"]
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "#RRGGBB" in str(exc.value)


def test_slide_substance_floor_ignores_framing_slide_types() -> None:
    # thesis / architecture / closing slides are exempt: a bare visual is fine.
    data = _valid_payload()
    data["sections"][0]["slides"][0]["visual"] = {"kind": "thesis"}  # thesis type
    data["sections"][3]["slides"][0]["visual"] = {"kind": "architecture"}  # arch type
    payload = StoryboardPayload.model_validate(data)
    assert payload.sections[0].slides[0].visual.kind == "thesis"


def test_slide_substance_floor_accepts_metric_descriptor() -> None:
    # A metric value/label counts as substance for a trust-type slide (index 4).
    data = _valid_payload()
    data["sections"][4]["slides"][0]["visual"] = {
        "kind": "metric",
        "value": "80% coverage",
        "label": "Gate",
    }
    payload = StoryboardPayload.model_validate(data)
    assert payload.sections[4].slides[0].visual.kind == "metric"


# ---------------------------------------------------------------------------
# P3.3 — truncation signature detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"title": "X", "theme": {"palette":', True),  # cut off mid-object
        ('{"a": 1, "b": [1, 2', True),  # truncated array, no closing brace
        ("not json at all", True),  # unparseable and unterminated
        ('{"a": 1}', False),  # complete valid JSON
        ('```json\n{"a": 1}\n```', False),  # complete, fenced
        ('{"a": 1} trailing chatter', False),  # complete + prose after (rfind }})
        ('{"a": 1,}', False),  # malformed but terminated -> normal repair, not retry
    ],
)
def test_looks_truncated(raw: str, expected: bool) -> None:
    assert looks_truncated(raw) is expected


def test_storyboard_prompt_names_canonical_payload_keys_and_bad_aliases() -> None:
    """The live model needs exact field names, not conceptual aliases."""

    assert STORYBOARD_PROMPT_VERSION == "storyboard-v1.5"
    required_keys = [
        "palette",
        "typography",
        "visible_text",
        "speaker_notes_ref",
        "source_map",
        '["SPEC", "PLAN"]',
        "source_refs",
        "demo_script_md",
        "technical_appendix_md",
        "renderer-supported",
        "video-demo",
        '"source_map"',
        '"slide_id"',
        '"backup_points"',
        "client, frontend, api, data, llm, integrations, trust, recovery",
    ]
    for key in required_keys:
        assert key in SYSTEM_PROMPT

    forbidden_aliases = [
        "colour_palette",
        "typography_mood",
        "text",
        "speaker_note_ref",
        "sourceMap",
        "url",
        "demo_script",
        "technical_appendix",
    ]
    for alias in forbidden_aliases:
        assert alias in SYSTEM_PROMPT

    for visual_kind in ALLOWED_VISUAL_KINDS:
        assert visual_kind in SYSTEM_PROMPT


def test_storyboard_repair_prompt_repeats_canonical_payload_keys() -> None:
    prompt = build_repair_user_prompt("{}", "theme.palette: Field required")
    for key in ("palette", "visible_text", "speaker_notes_ref", "source_map"):
        assert key in prompt
    for alias in ("colour_palette", "typography_mood", "text"):
        assert alias in prompt


# ---------------------------------------------------------------------------
# Section-count and forbidden-act rules
# ---------------------------------------------------------------------------


def test_rejects_more_than_six_sections() -> None:
    data = _valid_payload()
    data["sections"].append(
        {"id": "act-extra", "title": "Bonus", "slides": [_slide("sx", "product")]}
    )
    with pytest.raises(Exception):
        StoryboardPayload.model_validate(data)


def test_rejects_fewer_than_six_sections() -> None:
    data = _valid_payload()
    data["sections"] = data["sections"][:5]
    with pytest.raises(Exception):
        StoryboardPayload.model_validate(data)


def test_storyboard_schema_rejects_validation_or_execution_plan_top_level_acts() -> (
    None
):
    for bad_title in ("Validation", "Execution Plan"):
        data = _valid_payload()
        data["sections"][3]["title"] = bad_title
        with pytest.raises(Exception) as exc:
            StoryboardPayload.model_validate(data)
        assert (
            "top-level" in str(exc.value).lower()
            or "execution plan" in str(exc.value).lower()
        )


def test_rejects_out_of_order_titles() -> None:
    data = _valid_payload()
    data["sections"][0]["title"], data["sections"][1]["title"] = (
        data["sections"][1]["title"],
        data["sections"][0]["title"],
    )
    with pytest.raises(Exception):
        StoryboardPayload.model_validate(data)


# ---------------------------------------------------------------------------
# Architecture reveal
# ---------------------------------------------------------------------------


def test_storyboard_architecture_reveal_requires_core_layers() -> None:
    # storyboard-v1.5: dropping a *core* plane (client/api/data) is a failure.
    data = _valid_payload()
    data["diagrams"][0]["layers"] = [
        layer for layer in data["diagrams"][0]["layers"] if layer["kind"] != "data"
    ]
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "data" in str(exc.value).lower()


def test_storyboard_architecture_reveal_allows_missing_optional_layers() -> None:
    # Dropping an *optional* plane (recovery) is now valid — the product may not
    # have one, and fabricating it was the old failure mode.
    data = _valid_payload()
    data["diagrams"][0]["layers"] = [
        layer for layer in data["diagrams"][0]["layers"] if layer["kind"] != "recovery"
    ]
    StoryboardPayload.model_validate(data)


def test_storyboard_architecture_reveal_accepts_core_only_subset() -> None:
    # A CLI/batch product with only the three universal planes validates.
    data = _valid_payload()
    data["diagrams"][0]["layers"] = _arch_layers(CORE_ARCHITECTURE_LAYERS)
    StoryboardPayload.model_validate(data)


def test_storyboard_architecture_reveal_legacy_eight_layer_still_validates() -> None:
    # Pre-v1.5 decks carry all eight planes; they remain valid (8 superset core).
    data = _valid_payload()
    data["diagrams"][0]["layers"] = _arch_layers(ARCHITECTURE_LAYER_KINDS)
    StoryboardPayload.model_validate(data)


def test_core_and_optional_layers_partition_the_canonical_kinds() -> None:
    assert set(CORE_ARCHITECTURE_LAYERS) == {"client", "api", "data"}
    assert set(CORE_ARCHITECTURE_LAYERS).isdisjoint(OPTIONAL_ARCHITECTURE_LAYERS)
    assert set(CORE_ARCHITECTURE_LAYERS) | set(OPTIONAL_ARCHITECTURE_LAYERS) == set(
        ARCHITECTURE_LAYER_KINDS
    )


def test_requires_at_least_one_architecture_reveal() -> None:
    data = _valid_payload()
    data["diagrams"][0]["type"] = "flowchart"
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "architecture_reveal" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Slide sparseness
# ---------------------------------------------------------------------------


def test_rejects_overlong_headline() -> None:
    data = _valid_payload()
    data["sections"][0]["slides"][0]["headline"] = " ".join(["word"] * 19)
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "headline" in str(exc.value).lower()


def test_rejects_overlong_visible_text() -> None:
    data = _valid_payload()
    data["sections"][0]["slides"][0]["visible_text"] = " ".join(["word"] * 46)
    with pytest.raises(Exception):
        StoryboardPayload.model_validate(data)


def test_rejects_non_hex_palette() -> None:
    data = _valid_payload()
    data["theme"]["palette"] = ["red", "#2244FF", "#FFAA00"]
    with pytest.raises(Exception):
        StoryboardPayload.model_validate(data)


def test_rejects_unsupported_generated_visual_kinds() -> None:
    data = _valid_payload()
    for bad_kind in ("video-demo", "illustration", "infographic", "call-to-action"):
        data["sections"][0]["slides"][0]["visual"] = {"kind": bad_kind}
        with pytest.raises(Exception) as exc:
            StoryboardPayload.model_validate(copy.deepcopy(data))
        assert "visual.kind" in str(exc.value) or "visual" in str(exc.value).lower()


def test_rejects_generic_storyboard_titles() -> None:
    data = _valid_payload()
    data["title"] = "Product Launch Keynote"
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "generic" in str(exc.value).lower()


def test_rejects_video_demo_cues_and_scripts() -> None:
    data = _valid_payload()
    data["notes"]["s0"]["demo_cue"] = "Trigger video demonstration."
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(copy.deepcopy(data))
    assert "video demo" in str(exc.value).lower()

    data = _valid_payload()
    data["demo_script_md"] = "## Demo\nPlay the recorded demo video."
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "video demo" in str(exc.value).lower()


def test_rejects_generic_launch_copy_filler() -> None:
    data = _valid_payload()
    data["sections"][0]["slides"][0][
        "headline"
    ] = "Empower Your Business with Seamless Workflow Automation"
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "generic launch-copy" in str(exc.value).lower()

    data = _valid_payload()
    # Long enough to clear the talk_track length floor so the marketing-filler
    # check (not the min_length check) is what rejects it.
    data["notes"]["s0"]["talk_track"] = (
        "Open the slide and set the stage for the audience, then pivot hard into "
        "operational excellence as the throughline for everything that follows here."
    )
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "generic launch-copy" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Parse / repair flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_succeeds_without_repair() -> None:
    raw = json.dumps(_valid_payload())
    calls = 0

    async def _repair(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        return raw

    payload = await parse_and_validate_payload(raw, repair=_repair)
    assert payload.title == "Thought2Build Launch Keynote"
    assert calls == 0  # no repair needed


@pytest.mark.asyncio
async def test_parse_strips_markdown_fences() -> None:
    raw = "```json\n" + json.dumps(_valid_payload()) + "\n```"
    payload = await parse_and_validate_payload(raw)
    assert payload.title == "Thought2Build Launch Keynote"


@pytest.mark.asyncio
async def test_one_repair_attempt_then_success() -> None:
    bad = "not json at all"
    good = json.dumps(_valid_payload())
    calls = 0

    async def _repair(prompt: str) -> str:
        nonlocal calls
        calls += 1
        assert "VALIDATION ERRORS" in prompt
        return good

    payload = await parse_and_validate_payload(bad, repair=_repair)
    assert payload.title == "Thought2Build Launch Keynote"
    assert calls == 1


@pytest.mark.asyncio
async def test_no_second_repair_loop() -> None:
    bad = "still not json"
    calls = 0

    async def _repair(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        return "also not json"

    with pytest.raises(StoryboardPayloadError) as exc:
        await parse_and_validate_payload(bad, repair=_repair)
    assert calls == 1  # exactly one repair attempt, no loop
    assert exc.value.stage == "parse"


@pytest.mark.asyncio
async def test_failure_without_repair_raises_typed_error() -> None:
    data = _valid_payload()
    data["sections"] = data["sections"][:3]
    with pytest.raises(StoryboardPayloadError) as exc:
        await parse_and_validate_payload(json.dumps(data))
    assert exc.value.stage == "schema"
    # Redaction-safe: the summary is field locations/messages, not raw payload.
    assert "Launch Keynote" not in exc.value.summary


def test_error_summary_excludes_raw_input_values() -> None:
    from prompts.storyboard import _validate

    data = _valid_payload()
    data["title"] = "SECRET-TITLE-SHOULD-NOT-LEAK"
    data["sections"][0]["slides"][0]["headline"] = " ".join(["word"] * 30)
    with pytest.raises(StoryboardPayloadError) as exc:
        _validate(json.dumps(data))
    assert "SECRET-TITLE-SHOULD-NOT-LEAK" not in exc.value.summary


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_build_user_prompt_wraps_sources_and_problem() -> None:
    source = StoryboardSourcePackage(
        workspace_id=__import__("uuid").uuid4(),
        workspace_name="Thought2Build",
        problem_statement="Build a spec generator.",
        stage_versions={},
        artifacts={},
        excerpts={
            "PLAN:architecture": SourceExcerpt(
                source_id="PLAN:architecture",
                stage="plan",
                heading="Architecture",
                excerpt="FastAPI + Postgres + Redis.",
            )
        },
        missing_source_sections=[],
    )
    prompt = build_user_prompt(source)
    assert "Thought2Build" in prompt
    assert "PLAN:architecture" in prompt
    assert "untrusted_content" in prompt  # injection fence applied
    assert "FastAPI + Postgres + Redis." in prompt


def test_build_user_prompt_uses_spec_title_for_placeholder_workspace_name() -> None:
    source = StoryboardSourcePackage(
        workspace_id=__import__("uuid").uuid4(),
        workspace_name="Test 3",
        problem_statement="Build workflows.",
        stage_versions={},
        artifacts={"spec": "# Workflow Automation Platform\n\n## Overview\n..."},
        excerpts={
            "SPEC:overview": SourceExcerpt(
                source_id="SPEC:overview",
                stage="spec",
                heading="Overview",
                excerpt="Workflow Automation Platform overview.",
            )
        },
        missing_source_sections=[],
    )
    prompt = build_user_prompt(source)

    assert "PRODUCT NAME: Workflow Automation Platform" in prompt
    assert "WORKSPACE NAME: Test 3" in prompt


# ---------------------------------------------------------------------------
# Schema parity with the harness JSON schema
# ---------------------------------------------------------------------------


def test_pydantic_constants_match_harness_schema() -> None:
    schema = json.loads(_HARNESS_SCHEMA.read_text(encoding="utf-8"))
    text = _HARNESS_SCHEMA.read_text(encoding="utf-8")

    # Six exact act titles encoded as consts in the schema.
    for title in REQUIRED_SECTION_TITLES:
        assert f'"const": "{title}"' in text, f"schema missing act const {title!r}"

    # Section count: exactly six.
    sections = schema["properties"]["sections"]
    assert sections["minItems"] == 6 and sections["maxItems"] == 6

    # Title length and excerpt bound match the Pydantic Field constraints.
    assert schema["properties"]["title"]["maxLength"] == 200
    assert schema["$defs"]["source_ref"]["properties"]["excerpt"]["maxLength"] == 1200

    # Architecture-reveal layer kinds the schema enumerates are a superset of the
    # eight canonical kinds the Pydantic model recognises.
    layer_kinds = set(schema["$defs"]["diagram_layer"]["properties"]["kind"]["enum"])
    assert set(ARCHITECTURE_LAYER_KINDS).issubset(layer_kinds)

    # storyboard-v1.5 loosening (invariant 1.6: Pydantic subset of JSON schema).
    # Only the three core planes are required by both sides.
    arch = schema["$defs"]["architecture_reveal_diagram"]["allOf"][1]["properties"][
        "layers"
    ]
    assert arch["minItems"] == 3, "schema must require only the 3 core layers (v1.5)"
    contained = {
        clause["contains"]["properties"]["kind"]["const"] for clause in arch["allOf"]
    }
    assert contained == set(CORE_ARCHITECTURE_LAYERS)


def test_valid_payload_round_trips_through_pydantic_and_json() -> None:
    # The fixture we validate against the harness-aligned model is itself a
    # realistic payload (deep-copied so mutation tests never share state).
    payload = StoryboardPayload.model_validate(copy.deepcopy(_valid_payload()))
    dumped = payload.model_dump()
    assert StoryboardPayload.model_validate(dumped).title == payload.title

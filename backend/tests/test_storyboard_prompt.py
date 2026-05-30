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
    REQUIRED_ARCHITECTURE_LAYERS,
    REQUIRED_SECTION_TITLES,
    StoryboardPayload,
    StoryboardPayloadError,
    build_user_prompt,
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
        "visual": {"kind": "bullets"},
        "speaker_notes_ref": slide_id,
        "sources": ["PLAN"],
    }


def _note(slide_id: str) -> dict[str, Any]:
    return {
        "slide_id": slide_id,
        "talk_track": "Say this.",
        "transition": "Then move on.",
        "timing_seconds": 30,
        "pause_cue": "Pause here.",
        "demo_cue": "",
        "backup_points": ["A backup point"],
    }


def _architecture_reveal() -> dict[str, Any]:
    return {
        "id": "arch-reveal",
        "type": "architecture_reveal",
        "layers": [
            {
                "id": f"layer-{kind}",
                "kind": kind,
                "label": f"{kind} layer",
                "summary": "",
                "source_refs": [_source_ref()],
            }
            for kind in REQUIRED_ARCHITECTURE_LAYERS
        ],
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
        "title": "Launch Keynote",
        "theme": {
            "palette": ["#101010", "#2244FF", "#FFAA00"],
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


def test_storyboard_architecture_reveal_requires_layers() -> None:
    data = _valid_payload()
    # Drop the "recovery" layer.
    data["diagrams"][0]["layers"] = [
        layer for layer in data["diagrams"][0]["layers"] if layer["kind"] != "recovery"
    ]
    with pytest.raises(Exception) as exc:
        StoryboardPayload.model_validate(data)
    assert "recovery" in str(exc.value).lower()


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
    assert payload.title == "Launch Keynote"
    assert calls == 0  # no repair needed


@pytest.mark.asyncio
async def test_parse_strips_markdown_fences() -> None:
    raw = "```json\n" + json.dumps(_valid_payload()) + "\n```"
    payload = await parse_and_validate_payload(raw)
    assert payload.title == "Launch Keynote"


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
    assert payload.title == "Launch Keynote"
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
        workspace_name="SpecForge",
        problem_statement="Build a spec generator.",
        provider="anthropic",
        model="claude-sonnet-4-6",
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
    assert "SpecForge" in prompt
    assert "PLAN:architecture" in prompt
    assert "untrusted_content" in prompt  # injection fence applied
    assert "FastAPI + Postgres + Redis." in prompt


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
    # eight required kinds the Pydantic validator enforces.
    layer_kinds = set(schema["$defs"]["diagram_layer"]["properties"]["kind"]["enum"])
    assert set(REQUIRED_ARCHITECTURE_LAYERS).issubset(layer_kinds)


def test_valid_payload_round_trips_through_pydantic_and_json() -> None:
    # The fixture we validate against the harness-aligned model is itself a
    # realistic payload (deep-copied so mutation tests never share state).
    payload = StoryboardPayload.model_validate(copy.deepcopy(_valid_payload()))
    dumped = payload.model_dump()
    assert StoryboardPayload.model_validate(dumped).title == payload.title

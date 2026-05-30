"""Source-aware Storyboard validation tests.

These cover the service-level checks that need the dynamic source package:
schema validation can prove shape, but only the generation service knows which
source ids were actually extracted for this workspace.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from prompts.storyboard import (
    REQUIRED_ARCHITECTURE_LAYERS,
    StoryboardPayload,
    StoryboardPayloadError,
)
from services.pipeline.storyboard_service import _validate_payload_against_source
from services.pipeline.storyboard_source import SourceExcerpt, StoryboardSourcePackage


def _source_package() -> StoryboardSourcePackage:
    return StoryboardSourcePackage(
        workspace_id=uuid4(),
        workspace_name="SpecForge",
        problem_statement="Build a spec generator.",
        provider="anthropic",
        model="claude-sonnet-4-6",
        stage_versions={},
        artifacts={},
        excerpts={
            "SPEC:overview": SourceExcerpt(
                source_id="SPEC:overview",
                stage="spec",
                heading="Overview",
                excerpt="SpecForge turns an idea into a structured engineering spec.",
            ),
            "PLAN:architecture": SourceExcerpt(
                source_id="PLAN:architecture",
                stage="plan",
                heading="Architecture",
                excerpt="FastAPI, PostgreSQL, Redis, and a React SPA.",
            ),
        },
        missing_source_sections=[],
    )


def _payload() -> dict:
    sections = []
    notes = {}
    slide_types = (
        "thesis",
        "product",
        "walkthrough",
        "architecture",
        "trust",
        "closing",
    )
    section_titles = (
        "Opening Thesis",
        "Product Vision",
        "Product Walkthrough",
        "Technical Architecture",
        "Trust, Security, Reliability",
        "Launch Close",
    )
    for idx, title in enumerate(section_titles):
        slide_id = f"s{idx}"
        sections.append(
            {
                "id": f"act-{idx}",
                "title": title,
                "slides": [
                    {
                        "id": slide_id,
                        "type": slide_types[idx],
                        "headline": f"{title} headline",
                        "visible_text": "Sparse source-backed line.",
                        "visual": {"kind": slide_types[idx]},
                        "speaker_notes_ref": slide_id,
                        "sources": ["SPEC", "PLAN"],
                    }
                ],
            }
        )
        notes[slide_id] = {
            "slide_id": slide_id,
            "talk_track": "Talk through the source-backed point.",
            "transition": "Move forward.",
            "timing_seconds": 45,
            "pause_cue": "Pause briefly.",
            "demo_cue": "",
            "backup_points": ["Backup point."],
        }

    plan_ref = {
        "source": "PLAN",
        "source_id": "PLAN:architecture",
        "excerpt": "FastAPI, PostgreSQL, Redis, and a React SPA.",
    }
    return {
        "title": "SpecForge Launch Keynote",
        "theme": {
            "palette": ["#101418", "#1FB6FF", "#F5A623"],
            "typography": "Geometric sans",
            "motif": "Layered product glass",
            "transition_style": "Cinematic fades",
            "diagram_style": "Layered architecture planes",
        },
        "sections": sections,
        "diagrams": [
            {
                "id": "architecture-reveal",
                "type": "architecture_reveal",
                "layers": [
                    {
                        "id": f"layer-{kind}",
                        "kind": kind,
                        "label": f"{kind.title()} plane",
                        "summary": "Plane summary.",
                        "source_refs": [plan_ref],
                    }
                    for kind in REQUIRED_ARCHITECTURE_LAYERS
                ],
            }
        ],
        "source_map": {
            "opening-claim": [
                {
                    "source": "SPEC",
                    "source_id": "SPEC:overview",
                    "excerpt": (
                        "SpecForge turns an idea into a structured engineering spec."
                    ),
                }
            ]
        },
        "notes": notes,
        "demo_script_md": "## Walkthrough\n1. Open the workspace and show generation.",
        "technical_appendix_md": "## Appendix\nArchitecture and reliability backup.",
    }


def test_grounding_accepts_exact_source_ids() -> None:
    _validate_payload_against_source(
        StoryboardPayload.model_validate(_payload()), _source_package()
    )


def test_grounding_rejects_shallow_or_fabricated_source_ids() -> None:
    payload = _payload()
    payload["source_map"]["opening-claim"][0]["source_id"] = "SPEC"

    with pytest.raises(StoryboardPayloadError) as exc:
        _validate_payload_against_source(
            StoryboardPayload.model_validate(payload), _source_package()
        )

    assert exc.value.stage == "schema"
    assert "unavailable source_id" in exc.value.summary
    assert "SPEC:overview" in exc.value.summary


def test_grounding_rejects_mismatched_source_enum() -> None:
    payload = _payload()
    payload["diagrams"][0]["layers"][0]["source_refs"][0]["source"] = "SPEC"

    with pytest.raises(StoryboardPayloadError) as exc:
        _validate_payload_against_source(
            StoryboardPayload.model_validate(payload), _source_package()
        )

    assert "does not match" in exc.value.summary


def test_grounding_rejects_video_demo_language() -> None:
    payload = StoryboardPayload.model_validate(_payload())
    payload.demo_script_md = "## Walkthrough\nPlay the recorded demo video."

    with pytest.raises(StoryboardPayloadError) as exc:
        _validate_payload_against_source(payload, _source_package())

    assert "video demo" in exc.value.summary

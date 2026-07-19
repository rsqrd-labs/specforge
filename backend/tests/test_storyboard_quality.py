"""Unit tests for the deterministic Storyboard deck quality gate (P3.5).

Pure, no DB/Redis: ``assess_payload_quality`` is a pure function of a validated
``StoryboardPayload``. Each rule is exercised in isolation from a clean base
deck. Mutated fixtures are validated under the grandfather context so a deck can
deliberately fail a *quality* rule without first tripping the P3.4 Pydantic
substance floor (the quality gate is independent of that floor).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from prompts.storyboard import (
    GRANDFATHER_NOTE_DEPTH,
    StoryboardPayload,
    StoryboardPayloadError,
)
from services.pipeline.storyboard_quality import assess_payload_quality

_SECTION_TITLES = (
    "Opening Thesis",
    "Product Vision",
    "Product Walkthrough",
    "Technical Architecture",
    "Trust, Security, Reliability",
    "Launch Close",
)
_ACT_TYPES = ("thesis", "product", "walkthrough", "architecture", "trust", "closing")
_SR = {"source": "PLAN", "source_id": "PLAN:architecture", "excerpt": "x"}


def _note(slide_id: str, talk_track: str | None = None) -> dict[str, Any]:
    return {
        "slide_id": slide_id,
        "talk_track": talk_track
        or (
            "Open on the slide's single idea, name the concrete product capability "
            "from the finalised sources, explain why it matters to the audience, "
            "and land the takeaway before the next beat of the story."
        ),
        "transition": "Then move on.",
        "timing_seconds": 40,
        "pause_cue": "Pause here.",
        "demo_cue": "",
        "backup_points": ["A backup point.", "A second backup point."],
    }


def _visual(slide_idx: int) -> dict[str, Any]:
    if slide_idx % 2 == 0:
        return {"kind": "bullets", "points": ["One point", "Two point", "Three point"]}
    return {"kind": "metric", "value": "4 stages", "label": "Pipeline"}


def _slide(act_idx: int, slide_idx: int) -> dict[str, Any]:
    sid = f"s{act_idx}-{slide_idx}"
    return {
        "id": sid,
        "type": _ACT_TYPES[act_idx],
        "headline": f"Act {act_idx} slide {slide_idx} distinct headline",
        "visible_text": "Sparse supporting line.",
        "visual": _visual(slide_idx),
        "speaker_notes_ref": sid,
        "sources": ["PLAN"],
    }


def _clean_dict(slides_per_act: int = 2) -> dict[str, Any]:
    sections = []
    notes: dict[str, Any] = {}
    for a, title in enumerate(_SECTION_TITLES):
        slides = []
        for s in range(slides_per_act):
            sl = _slide(a, s)
            slides.append(sl)
            notes[sl["id"]] = _note(sl["id"])
        sections.append({"id": f"act-{a}", "title": title, "slides": slides})
    return {
        "title": "SpecForge Launch Keynote",
        "theme": {
            # 5 colours so non-grandfathered validations clear the L16 fresh-
            # generation palette floor.
            "palette": ["#101010", "#2244FF", "#FFAA00", "#F5F5F5", "#22CC88"],
            "typography": "Modern geometric sans",
            "motif": "Glass panels",
            "transition_style": "Smooth fades",
            "diagram_style": "Layered isometric",
        },
        "sections": sections,
        "diagrams": [
            {
                "id": "arch",
                "type": "architecture_reveal",
                "layers": [
                    {
                        "id": f"l-{k}",
                        "kind": k,
                        "label": f"{k} layer",
                        "summary": "",
                        "source_refs": [_SR],
                    }
                    for k in ("client", "api", "data")
                ],
            }
        ],
        "source_map": {
            "s0-0": [{"source": "SPEC", "source_id": "SPEC:overview", "excerpt": "x"}]
        },
        "notes": notes,
        "demo_script_md": "# Demo\n1. Show it.",
        "technical_appendix_md": "# Appendix\nBackup.",
    }


def _payload(data: dict[str, Any]) -> StoryboardPayload:
    # Grandfather so a fixture can fail a *quality* rule without first tripping the
    # P3.4 slide-substance / note-depth Pydantic floors.
    return StoryboardPayload.model_validate(
        data, context={GRANDFATHER_NOTE_DEPTH: True}
    )


# ---------------------------------------------------------------------------
# Clean deck
# ---------------------------------------------------------------------------


def test_clean_deck_has_no_findings() -> None:
    data = _clean_dict()
    # The clean base validates with NO grandfather (a genuinely floor-clean deck)
    # and the quality gate returns nothing.
    payload = StoryboardPayload.model_validate(data)
    assert assess_payload_quality(payload) == []


# ---------------------------------------------------------------------------
# Pacing: per-act count and deck total
# ---------------------------------------------------------------------------


def test_thin_deck_flagged() -> None:
    findings = assess_payload_quality(_payload(_clean_dict(slides_per_act=1)))
    assert any("6 slides" in f and "expected" in f for f in findings)


def test_overlong_act_flagged() -> None:
    data = _clean_dict()
    act = data["sections"][0]
    for extra in range(3):  # act 0 grows to 5 slides (> max 4)
        sid = f"s0-extra{extra}"
        act["slides"].append(
            {
                "id": sid,
                "type": "thesis",
                "headline": f"Extra {extra} distinct headline",
                "visible_text": "Sparse supporting line.",
                "visual": {"kind": "bullets", "points": ["a", "b", "c"]},
                "speaker_notes_ref": sid,
                "sources": ["PLAN"],
            }
        )
        data["notes"][sid] = _note(sid)
    findings = assess_payload_quality(_payload(data))
    assert any("'Opening Thesis' has 5 slides" in f for f in findings)


# ---------------------------------------------------------------------------
# Monotone visuals
# ---------------------------------------------------------------------------


def test_monotone_visuals_flagged() -> None:
    data = _clean_dict()
    for section in data["sections"]:
        for slide in section["slides"]:
            slide["visual"] = {"kind": "bullets", "points": ["a", "b", "c"]}
    findings = assess_payload_quality(_payload(data))
    assert any("distinct visual kind" in f for f in findings)


# ---------------------------------------------------------------------------
# Near-duplication: headline vs visible_text, talk track vs visible_text
# ---------------------------------------------------------------------------


def test_headline_restates_visible_text_flagged() -> None:
    data = _clean_dict()
    slide = data["sections"][0]["slides"][0]
    slide["headline"] = "The quick brown fox jumps over the lazy dog"
    slide["visible_text"] = "The quick brown fox jumps over the lazy dog"
    findings = assess_payload_quality(_payload(data))
    assert any("headline restates" in f and "s0-0" in f for f in findings)


def test_talk_track_echoes_visible_text_flagged() -> None:
    data = _clean_dict()
    line = "The quick brown fox jumps over the lazy dog beside the calm river"
    data["sections"][0]["slides"][0]["visible_text"] = line
    data["notes"]["s0-0"]["talk_track"] = f"{line} {line}"  # same tokens, > 120 chars
    findings = assess_payload_quality(_payload(data))
    assert any("talk track only echoes" in f and "s0-0" in f for f in findings)


def test_distinct_headline_and_talk_track_not_flagged() -> None:
    # A long talk track that genuinely adds depth around a short visible_text is
    # NOT a near-duplicate (its extra tokens inflate the Jaccard union).
    findings = assess_payload_quality(_payload(_clean_dict()))
    assert not any("echoes" in f or "restates" in f for f in findings)


# ---------------------------------------------------------------------------
# Interior-act substance backstop
# ---------------------------------------------------------------------------


def test_interior_act_without_substance_flagged() -> None:
    data = _clean_dict()
    # Turn "Product Vision" (interior) into framing-type slides with bare visuals:
    # thesis is exempt from the P3.4 floor, so this is Pydantic-valid, but the
    # quality gate's interior-act substance backstop must still fire.
    for slide in data["sections"][1]["slides"]:
        slide["type"] = "thesis"
        slide["visual"] = {"kind": "thesis"}
    findings = assess_payload_quality(_payload(data))
    assert any("Product Vision" in f and "points/metric" in f for f in findings)
    # Framing acts (Opening Thesis / Launch Close) are exempt from this backstop.
    assert not any("Opening Thesis" in f for f in findings)


def test_framing_acts_exempt_from_substance_backstop() -> None:
    data = _clean_dict()
    for act_idx in (0, 5):  # Opening Thesis, Launch Close
        for slide in data["sections"][act_idx]["slides"]:
            slide["type"] = "thesis" if act_idx == 0 else "closing"
            slide["visual"] = {"kind": slide["type"]}
    findings = assess_payload_quality(_payload(data))
    assert not any("no slide with a points/metric" in f for f in findings)


# ---------------------------------------------------------------------------
# Findings are content-free and never misclassified as transport errors
# ---------------------------------------------------------------------------


def test_findings_never_contain_transport_substrings() -> None:
    # A maximally broken deck: 1 slide/act (thin), monotone visuals, bare interior
    # acts. None of the findings may contain the substrings _payload_error_type
    # keys transport failures on, or the quality failure would skip escalation.
    data = _clean_dict(slides_per_act=1)
    for section in data["sections"]:
        for slide in section["slides"]:
            slide["type"] = "thesis"
            slide["visual"] = {"kind": "thesis"}
    findings = assess_payload_quality(_payload(data))
    assert findings  # it is indeed broken
    joined = " ".join(findings).lower()
    assert "provider" not in joined
    assert "timeout" not in joined
    assert "timed out" not in joined


def test_assess_is_pure_and_repeatable() -> None:
    data = _clean_dict(slides_per_act=1)
    payload = _payload(data)
    snapshot = copy.deepcopy(data)
    first = assess_payload_quality(payload)
    second = assess_payload_quality(payload)
    assert first == second
    assert data == snapshot  # no mutation of caller state


# ---------------------------------------------------------------------------
# Service wiring: _assert_deck_quality raises an ESCALATABLE quality failure
#
# The pure gate is proven above; these lock the integration the escalation path
# depends on. The real _parse_validate_and_ground/_assert_deck_quality path is
# otherwise only exercised by test_storyboard_service.py, which CI --ignores, so
# without these the classification invariant (a quality failure must escalate,
# not be mistaken for a transport error) has no CI-running proof.
# ---------------------------------------------------------------------------


def test_assert_deck_quality_raises_escalatable_failure_on_findings() -> None:
    from services.pipeline.storyboard_service import (
        _assert_deck_quality,
        _payload_error_type,
    )

    with pytest.raises(StoryboardPayloadError) as exc:
        _assert_deck_quality(_payload(_clean_dict(slides_per_act=1)))  # thin -> finding
    assert exc.value.stage == "schema"
    assert exc.value.summary.startswith("quality:")
    # The invariant escalation depends on: a quality failure is classified as a
    # (escalatable) schema failure, NOT a transport failure that skips escalation.
    assert _payload_error_type(exc.value) == "payload_schema"


def test_assert_deck_quality_passes_a_clean_deck() -> None:
    from services.pipeline.storyboard_service import _assert_deck_quality

    # No exception: a clean deck sails through the gate.
    _assert_deck_quality(StoryboardPayload.model_validate(_clean_dict()))

"""Refine is mode-aware, and mode-qualifying it must not disturb standard refines.

`_REFINE_STAGE_RULES` is keyed by stage type only, so a Demo Day tasks refine was
told to preserve a `Dependencies` field Demo Day does not have, and was told
nothing about `Precondition:` / `Estimated minutes:` — the two fields the Demo
Day construction verifier joins on (C1 dag_acyclic, C5 time_budget). A refine
could rename or drop them and silently turn a verified package red.

The second half of this file is the cache-safety pin: the refine generation cache
key carries no `mode` field, so a mode-dependent prompt without a mode-dependent
version would let a Demo Day refine replay a standard refine's cached output.
"""

from __future__ import annotations

import pytest

from services.pipeline.stage_manager import (
    _REFINE_STAGE_RULES,
    REFINE_PROMPT_VERSION,
    _refine_stage_rules,
    refine_prompt_version,
)


@pytest.mark.parametrize("stage_type", ["spec", "plan", "harness", "tasks"])
def test_standard_refine_rules_are_byte_identical(stage_type: str) -> None:
    """The regression pin: standard mode is the 99% path and must not move."""
    assert _refine_stage_rules(stage_type, "standard") == _REFINE_STAGE_RULES.get(
        stage_type, ""
    )


@pytest.mark.parametrize("mode", ["standard", "", "unknown-mode"])
def test_unknown_modes_fall_back_to_standard(mode: str) -> None:
    assert _refine_stage_rules("tasks", mode) == _REFINE_STAGE_RULES["tasks"]


def test_demo_day_tasks_refine_protects_the_fields_the_verifier_joins_on() -> None:
    rules = _refine_stage_rules("tasks", "demo_day")
    # Everything the standard rule said still applies…
    assert rules.startswith(_REFINE_STAGE_RULES["tasks"])
    # …plus the Demo Day join keys.
    assert "Precondition:" in rules
    assert "Estimated minutes:" in rules
    assert "there is no Dependencies field" in " ".join(rules.split())


def test_demo_day_plan_refine_protects_the_plan_coverage_sections() -> None:
    rules = " ".join(_refine_stage_rules("plan", "demo_day").split())
    assert rules.startswith(" ".join(_REFINE_STAGE_RULES["plan"].split()))
    for phrase in (
        "REAL/MOCKED",
        "Demo surface",
        "seed dataset",
        "auth stance",
    ):
        assert phrase in rules


def test_demo_day_gets_no_extra_rules_where_it_has_no_extra_fields() -> None:
    """Spec and harness carry the same structural fields in both modes, so they
    must stay byte-identical rather than accrete mode text for its own sake."""
    for stage_type in ("spec", "harness"):
        assert (
            _refine_stage_rules(stage_type, "demo_day")
            == _REFINE_STAGE_RULES[stage_type]
        )


def test_standard_refine_cache_key_version_is_unchanged() -> None:
    """Standard refines must not be invalidated by the Demo Day addition."""
    assert refine_prompt_version("standard") == REFINE_PROMPT_VERSION
    assert refine_prompt_version("anything-else") == REFINE_PROMPT_VERSION


def test_demo_day_refine_cannot_replay_a_standard_refines_cached_output() -> None:
    """The cache key has no `mode` field; the version has to carry it instead."""
    assert refine_prompt_version("demo_day") != REFINE_PROMPT_VERSION
    assert refine_prompt_version("demo_day").startswith(REFINE_PROMPT_VERSION)

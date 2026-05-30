"""T-248 — zero-LLM section-presence validator tests."""

from __future__ import annotations

import time

import pytest

from services.pipeline.artifact_validator import (
    SECTION_CONTRACTS,
    MissingSectionError,
    validate_sections,
)


def _complete_plan_artifact() -> str:
    """A PLAN.md body containing every required base heading (no conditional)."""
    return "\n\n".join(
        f"{heading}\nbody text\n" for heading in SECTION_CONTRACTS["plan"]
    )


def test_validate_sections_passes_when_all_present() -> None:
    # All base headings present, no UI sentinel in deps → no error.
    validate_sections("plan", _complete_plan_artifact(), {})


def test_validate_sections_lists_all_missing() -> None:
    # Drop two headings; the error must report BOTH (no short-circuit).
    dropped = {"## Capacity Model", "## API Design"}
    artifact = "\n\n".join(
        f"{heading}\nbody\n"
        for heading in SECTION_CONTRACTS["plan"]
        if heading not in dropped
    )
    with pytest.raises(MissingSectionError) as excinfo:
        validate_sections("plan", artifact, {})
    assert set(excinfo.value.missing) == dropped
    assert excinfo.value.stage_type == "plan"


def test_validate_sections_frontend_conditional_fires_on_ui_sentinel() -> None:
    # Complete base artifact but no Frontend Architecture; deps mention a UI.
    artifact = _complete_plan_artifact()
    assert "## Frontend Architecture" not in artifact
    deps = {"spec": "The product is a web dashboard for managing projects."}
    with pytest.raises(MissingSectionError) as excinfo:
        validate_sections("plan", artifact, deps)
    assert excinfo.value.missing == ["## Frontend Architecture"]


def test_validate_sections_frontend_conditional_skipped_when_no_sentinel() -> None:
    # Same artifact (no Frontend Architecture); deps describe a non-UI surface.
    artifact = _complete_plan_artifact()
    deps = {"spec": "A nightly batch ETL job ingesting CSV files into a warehouse."}
    # No UI sentinel → Frontend Architecture not required → no error.
    validate_sections("plan", artifact, deps)


def test_validate_sections_unknown_stage_is_noop() -> None:
    # A stage with no contract never raises.
    validate_sections("unknown", "", {})


def test_validate_sections_runs_in_under_5ms_on_200k_artifact() -> None:
    # ~210K-char artifact containing every plan heading + the conditional one.
    artifact = (
        _complete_plan_artifact()
        + "\n## Frontend Architecture\nbody\n"
        + ("\nfiller content line " * 11000)
    )
    assert len(artifact) > 200_000
    deps = {"spec": "web dashboard"}  # also exercises the conditional sentinel path

    validate_sections("plan", artifact, deps)  # warm up
    best = min(
        _time_one(lambda: validate_sections("plan", artifact, deps)) for _ in range(5)
    )
    assert best < 0.005, f"validator took {best * 1000:.2f} ms (budget 5 ms)"


def _time_one(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start

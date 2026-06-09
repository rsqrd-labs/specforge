"""T-248 — zero-LLM section-presence validator tests."""

from __future__ import annotations

import time

import pytest

from services.pipeline.artifact_validator import (
    SECTION_CONTRACTS,
    IncompleteArtifactError,
    MissingSectionError,
    chunk_completion_sentinel,
    strip_completion_sentinel,
    validate_artifact_completeness,
    validate_completion_sentinel,
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


def test_validate_completion_sentinel_requires_final_line() -> None:
    artifact = "## Overview\nDetailed content"
    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_completion_sentinel("spec", artifact, chunk_key="product-scope")
    assert excinfo.value.issues[0].code == "missing_completion_sentinel"


def test_strip_completion_sentinel_removes_internal_marker() -> None:
    artifact = (
        "## Overview\nDetailed content\n"
        f"{chunk_completion_sentinel('spec', 'product-scope')}"
    )
    validate_completion_sentinel("spec", artifact, chunk_key="product-scope")
    assert strip_completion_sentinel("spec", artifact, chunk_key="product-scope") == (
        "## Overview\nDetailed content"
    )


def test_validate_artifact_completeness_rejects_shallow_required_section() -> None:
    detailed = "Detailed content that is specific enough for validation."
    artifact = "\n\n".join(
        f"{heading}\n{'body' if heading == '## Overview' else detailed}"
        for heading in SECTION_CONTRACTS["spec"]
    )
    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("spec", artifact)
    assert excinfo.value.issues[0].code == "shallow_required_section"


def test_validate_artifact_completeness_rejects_incomplete_harness_file() -> None:
    artifact = "\n\n".join(
        [
            "## Harness Overview\nDetailed harness strategy and commands.",
            "## Requirement-to-Test Matrix\nDetailed mapping table for FR-001.",
            "## Coverage Plan\nDetailed unit and integration coverage plan.",
            "## File Tree\nharness/tests/test_auth.py",
            "## Files\n### File: harness/tests/test_auth.py\n```python\n",
        ]
    )
    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("harness", artifact)
    codes = {issue.code for issue in excinfo.value.issues}
    assert "unbalanced_code_fence" in codes
    assert "incomplete_harness_file_block" in codes


def test_validate_artifact_completeness_rejects_incomplete_task_block() -> None:
    overview = "\n\n".join(
        f"{heading}\nDetailed content that is specific enough for validation."
        for heading in SECTION_CONTRACTS["tasks"]
    )
    artifact = f"{overview}\n\n### T-001: Create users\n**Phase:** Data Layer\n"
    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("tasks", artifact)
    assert any(issue.code == "incomplete_task_block" for issue in excinfo.value.issues)


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

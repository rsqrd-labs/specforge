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


# A Mermaid/ASCII diagram is exactly what the spec prompt asks for in the User
# Flow Diagrams section.  Regression: the depth normaliser used to strip the
# entire fenced block, so a diagram-only section read as empty and tripped a
# spurious shallow finding that refunded nearly every spec.
_DIAGRAM_BODY = (
    "The primary flow from sign-in to a generated spec.\n\n"
    "```mermaid\n"
    "flowchart TD\n"
    "  A[Landing] --> B[Sign in with Google]\n"
    "  B --> C{Has workspace?}\n"
    "  C -->|yes| D[Dashboard]\n"
    "  C -->|no| E[Create workspace]\n"
    "  E --> D\n"
    "  D --> F[Generate spec]\n"
    "```\n"
)


def test_diagram_only_section_counts_as_substantive() -> None:
    detailed = "Detailed content that is specific enough for validation."
    artifact = "\n\n".join(
        f"{heading}\n"
        f"{_DIAGRAM_BODY if heading == '## User Flow Diagrams' else detailed}"
        for heading in SECTION_CONTRACTS["spec"]
    )
    # The diagram body is real substance, so no shallow finding for it.  (Other
    # spec-specific checks like requirement-ID floors may still fire on this
    # minimal fixture; we only assert the diagram section itself is not flagged.)
    try:
        validate_artifact_completeness("spec", artifact)
    except IncompleteArtifactError as exc:
        shallow_refs = {
            issue.reference
            for issue in exc.issues
            if issue.code == "shallow_required_section"
        }
        assert "## User Flow Diagrams" not in shallow_refs


def test_refundable_partition_separates_truncation_from_depth() -> None:
    from services.pipeline.artifact_validator import CompletenessIssue

    truncated = CompletenessIssue("provider_stopped_by_limit", "stopped")
    shallow = CompletenessIssue("shallow_required_section", "thin", "## Risks")
    assert truncated.is_refundable is True
    assert shallow.is_refundable is False

    exc = IncompleteArtifactError("spec", [truncated, shallow])
    assert exc.truncation_issues == [truncated]
    assert exc.depth_issues == [shallow]


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


def test_validate_artifact_completeness_rejects_spec_without_evidence() -> None:
    artifact = "\n\n".join(
        (
            f"{heading}\nDetailed section content with enough product detail for "
            "the validator to treat it as substantive."
        )
        for heading in SECTION_CONTRACTS["spec"]
    )
    artifact = artifact.replace(
        "## Functional Requirements\nDetailed section content with enough product "
        "detail for the validator to treat it as substantive.",
        (
            "## Functional Requirements\n"
            "| ID | Requirement |\n"
            "|---|---|\n"
            "| FR-001 | User can create a project. |"
        ),
    )

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("spec", artifact)

    assert any(
        issue.code == "missing_evidence_contract" for issue in excinfo.value.issues
    )


def test_validate_artifact_completeness_rejects_plan_missing_rtm_id() -> None:
    artifact = (
        _complete_plan_artifact()
        .replace(
            "## Requirement Traceability Matrix\nbody text",
            (
                "## Requirement Traceability Matrix\n"
                "| Source ID | Requirement summary | Design response "
                "| Verification method | Residual risk |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | Create project. | POST /projects. | contract test | Low |"
            ),
        )
        .replace(
            "## Security Architecture\nbody text",
            (
                "## Security Architecture\n"
                "SEC-001 authentication is enforced by middleware."
            ),
        )
    )

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness(
            "plan",
            artifact,
            {"spec": "FR-001 creates projects. SEC-001 requires authentication."},
        )

    assert any(
        issue.code == "rtm_missing_upstream_id" for issue in excinfo.value.issues
    )


def test_validate_artifact_completeness_rejects_missing_harness_tree_block() -> None:
    artifact = "\n\n".join(
        [
            "## Harness Overview\nDetailed harness strategy and local commands.",
            (
                "## Requirement-to-Test Matrix\n"
                "| Source ID | Test file | Test name |\n"
                "|---|---|---|\n"
                "| FR-001 | tests/test_projects.py | test_create_project |"
            ),
            (
                "## Coverage Plan\nDetailed integration, security, contract, "
                "and migration_safety coverage."
            ),
            (
                "## File Tree\n```text\n"
                "harness/tests/test_projects.py\n"
                "harness/tests/test_missing.py\n"
                "```"
            ),
            (
                "## Files\n"
                "### File: harness/tests/test_projects.py\n"
                "```python\n"
                "# Tests: FR-001\n"
                "def test_create_project():\n"
                "    assert False, 'not implemented: FR-001'\n"
                "```"
            ),
        ]
    )

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("harness", artifact)

    assert any(
        issue.code == "harness_file_tree_missing_block"
        for issue in excinfo.value.issues
    )


def test_validate_artifact_completeness_rejects_missing_task_harness_ref() -> None:
    artifact = _complete_tasks_artifact(
        harness_ref="`tests/test_projects.py::test_missing_project`"
    )
    harness = _harness_with_test("tests/test_projects.py", "test_create_project")

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness(
            "tasks",
            artifact,
            {"spec": "FR-001 creates projects.", "harness": harness},
        )

    assert any(
        issue.code == "task_harness_ref_not_found" for issue in excinfo.value.issues
    )


def test_validate_artifact_completeness_rejects_effort_summary_mismatch() -> None:
    artifact = _complete_tasks_artifact(
        task_count_line="Tasks: 2 total - 2 MUST - 0 SHOULD - 0 COULD"
    )

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("tasks", artifact, {"spec": "FR-001"})

    assert any(
        issue.code == "effort_summary_task_count_mismatch"
        for issue in excinfo.value.issues
    )


def test_validate_artifact_completeness_rejects_future_task_dependency() -> None:
    artifact = _complete_tasks_artifact(dependencies="T-002")

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("tasks", artifact, {"spec": "FR-001"})

    assert any(
        issue.code == "invalid_task_dependency_order" for issue in excinfo.value.issues
    )


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


def _harness_with_test(path: str, test_name: str) -> str:
    return (
        "## Harness Overview\nDetailed harness strategy.\n\n"
        "## Requirement-to-Test Matrix\n"
        f"| FR-001 | {path} | {test_name} |\n\n"
        "## Coverage Plan\nDetailed coverage.\n\n"
        f"## File Tree\n```text\nharness/{path}\n```\n\n"
        f"## Files\n### File: harness/{path}\n"
        "```python\n"
        "# Tests: FR-001\n"
        f"def {test_name}():\n"
        "    assert False, 'not implemented: FR-001'\n"
        "```"
    )


def _complete_tasks_artifact(
    *,
    harness_ref: str = "`tests/test_projects.py::test_create_project`",
    task_count_line: str = "Tasks: 1 total - 1 MUST - 0 SHOULD - 0 COULD",
    dependencies: str = "None",
) -> str:
    overview = "\n\n".join(
        [
            (
                "## Effort Summary\n"
                "- Estimate range: ~1 week\n"
                f"- {task_count_line}\n"
                "- Sizes: 1xM\n"
                "- Minimum cut: Ship MUST-only -> ~2d"
            ),
            (
                "## Execution Overview\n"
                "Detailed implementation order with safe sequencing."
            ),
            (
                "## Traceability Overview\n"
                "| Source ID | Plan section | Harness tests | Task IDs | "
                "Completion evidence |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | API Design | test_create_project | T-001 | pytest passes |"
            ),
            "## Dependency Graph\n```mermaid\ngraph TD\n  T001\n```",
            "## Task Sizing Legend\nM means one to three days with focused tests.",
        ]
    )
    return (
        f"{overview}\n\n"
        "## Phase 1: API Layer\n\n"
        "### T-001: Implement Project Creation\n\n"
        "**Phase:** API Layer\n"
        "**Spec refs:** FR-001\n"
        "**Plan refs:** API Design, Data Model and Persistence\n"
        f"**Harness refs:** {harness_ref}\n"
        "**Priority:** MUST\n"
        "**Estimate:** M\n"
        "**Estimated size:** M\n"
        "**Risk:** Medium - project creation is a core workflow\n"
        "**Owner:** Backend\n\n"
        "**Description**\n"
        "Implement the project creation workflow with validation and persistence.\n\n"
        "**Inputs**\n"
        "- Plan API contract and harness test.\n\n"
        "**Outputs**\n"
        "- Project creation endpoint and passing harness test.\n\n"
        "**Steps**\n"
        "1. Create the project service and route from the plan contract.\n\n"
        "**Acceptance Criteria**\n"
        "1. `pytest tests/test_projects.py::test_create_project -q` passes.\n\n"
        "**Rollback / Recovery**\n"
        "Pure code change; revert the route and service if needed.\n\n"
        "**Dependencies:** "
        f"{dependencies}\n"
    )


def test_validate_artifact_completeness_enforces_spec_id_floors() -> None:
    """A spec whose requirement coverage collapses to a couple of IDs is a
    depth failure even when every heading and evidence contract is present."""
    import re as _re

    import artifact_fixtures

    degraded = _re.sub(r"\bFR-00[2-9]\b", "FR-001", artifact_fixtures.VALID_SPEC)
    degraded = _re.sub(r"\bNFR-00[2-9]\b", "NFR-001", degraded)
    degraded = _re.sub(r"\bAC-00[2-9]\b", "AC-001", degraded)

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("spec", degraded)

    insufficient = [
        issue
        for issue in excinfo.value.issues
        if issue.code == "insufficient_requirement_ids"
    ]
    assert {issue.reference for issue in insufficient} == {"FR", "NFR", "AC"}

    # The full fixture clears the floors.
    validate_artifact_completeness("spec", artifact_fixtures.VALID_SPEC)


def test_validate_artifact_completeness_enforces_minimum_task_count() -> None:
    artifact = _complete_tasks_artifact()

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("tasks", artifact, {"spec": "FR-001"})

    assert any(
        issue.code == "insufficient_task_count" for issue in excinfo.value.issues
    )


def test_min_body_chars_floors_catch_heading_restatements() -> None:
    """A one-clause body under a required heading is shallow at every stage."""
    from services.pipeline.artifact_validator import _min_body_chars

    assert _min_body_chars("spec") >= 120
    assert _min_body_chars("plan") >= 150
    assert _min_body_chars("harness") >= 60
    assert _min_body_chars("tasks") >= 50

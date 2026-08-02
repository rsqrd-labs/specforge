"""T-248 — zero-LLM section-presence validator tests."""

from __future__ import annotations

import time

import pytest

from services.pipeline.artifact_validator import (
    SECTION_CONTRACTS,
    IncompleteArtifactError,
    MissingSectionError,
    chunk_completion_sentinel,
    dedupe_file_blocks,
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


# A body comfortably above the 150-char plan depth floor so every base section
# clears `_section_body_issues` and only the section-under-test can be the cause
# of a `shallow_required_section` finding.
_DEEP_SECTION_BODY = (
    "This section states the concrete design decision, the requirement it "
    "satisfies, the chosen mechanism plus one credible alternative, the failure "
    "mode and recovery path, and the observability signal that proves it works."
)


def _deep_plan_artifact(*, frontend_body: str | None = None) -> str:
    """A PLAN.md where every base section has a substantive body.

    Used to prove a *specific* section is (not) falsely flagged shallow without
    other sections muddying the result. When ``frontend_body`` is given the
    conditional ``## Frontend Architecture`` section is appended with that body.
    """
    parts = [
        f"{heading}\n{_DEEP_SECTION_BODY}\n" for heading in SECTION_CONTRACTS["plan"]
    ]
    if frontend_body is not None:
        parts.append(f"## Frontend Architecture\n{frontend_body}\n")
    return "\n\n".join(parts)


def test_plan_contract_aqa_heading_matches_prompt_heading() -> None:
    # Audit finding #1 root cause: the SECTION_CONTRACTS entry must be the FULL
    # heading the plan prompt actually emits, so the line-anchored _section_body
    # extraction matches (a truncated entry passes the substring gate but extracts
    # an empty body → false shallow advisory on every plan). Pin the contract and
    # the prompt to the same literal so they can never drift again.
    from prompts.plan import SYSTEM_PROMPT

    heading = "## Architecture Quality Attribute Matrix"
    assert heading in SECTION_CONTRACTS["plan"]
    assert heading in SYSTEM_PROMPT


def test_architecture_quality_attribute_matrix_not_falsely_shallow() -> None:
    # Audit finding #1: the contract heading is the FULL "Architecture Quality
    # Attribute Matrix", so its line-anchored body extraction succeeds and the
    # section is never falsely flagged shallow on every plan. Every section here
    # has a deep body and there are no upstream deps to drive other plan checks,
    # so a correct validator raises nothing.
    artifact = _deep_plan_artifact()
    assert "## Architecture Quality Attribute Matrix" in artifact
    validate_artifact_completeness("plan", artifact, {})


def test_frontend_architecture_not_applicable_one_liner_is_valid() -> None:
    # Audit finding #2: a backend/CLI plan may answer the conditional Frontend
    # Architecture section with the prompt-blessed "Not applicable because ..."
    # one-liner. The deps mention "console"/"app" so the sentinel fires and the
    # section is required — yet the blessed one-liner must NOT be flagged shallow.
    artifact = _deep_plan_artifact(
        frontend_body="Not applicable because this is a backend-only CLI service."
    )
    deps = {"spec": "A command-line console app with no browser surface."}
    validate_artifact_completeness("plan", artifact, deps)


def test_frontend_architecture_genuinely_shallow_still_flagged() -> None:
    # The finding-#2 exemption is narrow: a conditional section that is in scope
    # (sentinel fired) but has a thin, non-"Not applicable" body is still shallow.
    artifact = _deep_plan_artifact(frontend_body="See above.")
    deps = {"spec": "A web dashboard with screens and pages."}
    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("plan", artifact, deps)
    assert any(
        issue.code == "shallow_required_section"
        and issue.reference == "## Frontend Architecture"
        for issue in excinfo.value.issues
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
# Flows section.  Regression: the depth normaliser used to strip the
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
        f"{heading}\n" f"{_DIAGRAM_BODY if heading == '## User Flows' else detailed}"
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
        assert "## User Flows" not in shallow_refs


def test_refundable_partition_separates_truncation_from_depth() -> None:
    from services.pipeline.artifact_validator import CompletenessIssue

    truncated = CompletenessIssue("provider_stopped_by_limit", "stopped")
    shallow = CompletenessIssue("shallow_required_section", "thin", "## Risks")
    assert truncated.is_refundable is True
    assert shallow.is_refundable is False

    exc = IncompleteArtifactError("spec", [truncated, shallow])
    assert exc.truncation_issues == [truncated]
    assert exc.depth_issues == [shallow]


def test_only_provider_facts_are_refundable() -> None:
    # The refund discriminator is narrowed to the two objective provider-reported
    # facts.  Everything else — a missing internal sentinel, an unbalanced fence,
    # an incomplete harness file block — is a heuristic the user owns, never a
    # refund or rerun (the false-refund + rerun bleed fix).
    from services.pipeline.artifact_validator import CompletenessIssue

    refundable = {"empty_artifact", "provider_stopped_by_limit"}
    advisory = {
        "missing_completion_sentinel",
        "unbalanced_code_fence",
        "incomplete_harness_file_block",
        "shallow_required_section",
        "dangling_trailing_line",
    }
    for code in refundable:
        assert CompletenessIssue(code, "x").is_refundable is True
    for code in advisory:
        assert CompletenessIssue(code, "x").is_refundable is False


def test_artifact_ending_on_complete_table_is_not_dangling() -> None:
    # A plan that legitimately closes on a markdown table (e.g. an "Open
    # Questions" matrix) ends every row with '|'. That trailing pipe must NOT be
    # read as a mid-table truncation — the regression that blocked a complete
    # 174k-char plan as incomplete_output and refunded it.
    from services.pipeline.artifact_validator import _markdown_shape_issues

    artifact = (
        "## Open Questions\n\n"
        "| ID | Question | Owner |\n"
        "| --- | --- | --- |\n"
        "| OQ-001 | Is the control surface admin-only? | Security owner |"
    )
    codes = {issue.code for issue in _markdown_shape_issues(artifact)}
    assert "dangling_trailing_line" not in codes


def test_artifact_ending_mid_clause_is_still_flagged_but_not_refundable() -> None:
    # A mid-clause-looking tail (trailing colon or comma) is still *surfaced* as a
    # dangling_trailing_line finding — but it is NOT refundable.  The check only
    # runs after the completion sentinel passed (the model asserted completeness),
    # so a trailing colon/comma is a heuristic opinion on a complete artifact, not
    # genuine truncation: it flows through as a non-blocking advisory finding.
    from services.pipeline.artifact_validator import (
        CompletenessIssue,
        _markdown_shape_issues,
    )

    for tail in ("The remaining risks are:", "first item, second item,"):
        issues = _markdown_shape_issues(f"## Risks\n\n{tail}")
        codes = {issue.code for issue in issues}
        assert "dangling_trailing_line" in codes
        assert all(not issue.is_refundable for issue in issues)

    # Exhaustive guard: the code itself must never be classed as refundable.
    assert CompletenessIssue("dangling_trailing_line", "x").is_refundable is False


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


def test_matrix_missing_file_is_language_agnostic() -> None:
    """A TS/Vitest matrix row pointing at an unemitted file is caught.

    The legacy `harness_matrix_missing_test` keys on the pytest `test_` prefix
    and silently no-ops on non-Python harnesses; the file-path check does not.
    """
    artifact = "\n\n".join(
        [
            "## Harness Overview\nDetailed harness strategy and local commands.",
            (
                "## Requirement-to-Test Matrix\n"
                "| Source ID | Test file | Test name |\n"
                "|---|---|---|\n"
                "| FR-001 | `tests/admin.test.ts` | `admin_config_updates` |\n"
                "| NFR-001 | `tests/performance/perf.test.ts` "
                "| `latency_budget_enforced` |"
            ),
            (
                "## Coverage Plan\nDetailed integration, security, contract, "
                "and migration_safety coverage."
            ),
            "## File Tree\n```text\nharness/tests/admin.test.ts\n```",
            (
                "## Files\n"
                "### File: harness/tests/admin.test.ts\n"
                "```ts\n"
                "// Tests: FR-001\n"
                "it('admin_config_updates', () => { expect(false).toBe(true); });\n"
                "```"
            ),
        ]
    )

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("harness", artifact)

    missing = [
        issue
        for issue in excinfo.value.issues
        if issue.code == "harness_matrix_missing_file"
    ]
    assert missing, "expected a matrix→file integrity failure"
    assert "tests/performance/perf.test.ts" in missing[0].reference
    # The covered file must NOT be reported as missing.
    assert "tests/admin.test.ts" not in missing[0].reference
    # harness_matrix_missing_file is advisory: not in the refundable set.
    assert all(not issue.is_refundable for issue in missing)


def test_dedupe_file_blocks_removes_doubled_files_section() -> None:
    """A harness whose ## Files section was emitted twice is self-healed."""
    file_block = (
        "### File: harness/tests/a.test.ts\n```ts\nit('a', () => {});\n```\n"
        "### File: harness/tests/b.test.ts\n```ts\nit('b', () => {});\n```\n"
    )
    artifact = (
        "## Harness Overview\nStrategy.\n\n"
        "## Files\n" + file_block + file_block  # doubled
    )

    deduped, removed = dedupe_file_blocks(artifact)

    assert removed == 2
    assert deduped.count("### File: harness/tests/a.test.ts") == 1
    assert deduped.count("### File: harness/tests/b.test.ts") == 1
    # The Overview heading above ## Files is untouched.
    assert "## Harness Overview" in deduped


def test_dedupe_file_blocks_noop_without_duplicates() -> None:
    artifact = (
        "## Files\n"
        "### File: harness/tests/a.test.ts\n```ts\nit('a', () => {});\n```\n"
    )
    deduped, removed = dedupe_file_blocks(artifact)
    assert removed == 0
    assert deduped == artifact


def test_dedupe_file_blocks_noop_for_non_harness() -> None:
    spec = "## Overview\nA product spec with no File blocks at all."
    deduped, removed = dedupe_file_blocks(spec)
    assert removed == 0
    assert deduped == spec


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


def test_validate_artifact_completeness_flags_self_dependency_cycle() -> None:
    # A task that depends on itself is a one-node cycle: an unresolvable order.
    artifact = _complete_tasks_artifact(dependencies="T-001")

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("tasks", artifact, {"spec": "FR-001"})

    assert any(
        issue.code == "invalid_task_dependency_order" for issue in excinfo.value.issues
    )


def test_validate_artifact_completeness_allows_forward_task_dependency() -> None:
    # A forward reference between two EXISTING tasks (T-001 -> T-002) is a valid
    # acyclic order — a model may number tasks by feature area, not strict
    # execution order. It must NOT be flagged (audit finding #5: the old
    # dep_num >= task_num heuristic falsely did).
    artifact = _two_task_artifact(
        first_dependencies="T-002", second_dependencies="None"
    )

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("tasks", artifact, {"spec": "FR-001"})

    assert not any(
        issue.code == "invalid_task_dependency_order" for issue in excinfo.value.issues
    )


def test_validate_artifact_completeness_flags_two_node_dependency_cycle() -> None:
    # T-001 -> T-002 and T-002 -> T-001 is a genuine circular dependency.
    artifact = _two_task_artifact(
        first_dependencies="T-002", second_dependencies="T-001"
    )

    with pytest.raises(IncompleteArtifactError) as excinfo:
        validate_artifact_completeness("tasks", artifact, {"spec": "FR-001"})

    cyclic = [
        issue
        for issue in excinfo.value.issues
        if issue.code == "invalid_task_dependency_order"
    ]
    assert cyclic, "a mutual T-001 <-> T-002 dependency must be flagged"
    assert "T-001" in cyclic[0].detail and "T-002" in cyclic[0].detail


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


def _two_task_artifact(*, first_dependencies: str, second_dependencies: str) -> str:
    """A two-task TASKS.md so the dependency *graph* (not numbering) is exercised.

    Both T-001 and T-002 exist, so a forward reference is a valid acyclic order
    while a mutual reference is a real cycle. Used by the finding-#5 tests.
    """

    def _block(num: int, title: str, dependencies: str) -> str:
        return (
            f"### T-{num:03d}: {title}\n\n"
            f"**Phase:** API Layer\n"
            "**Spec refs:** FR-001\n"
            "**Plan refs:** API Design, Data Model and Persistence\n"
            "**Harness refs:** `tests/test_projects.py::test_create_project`\n"
            "**Priority:** MUST\n"
            "**Estimate:** M\n"
            "**Estimated size:** M\n"
            "**Risk:** Medium - core workflow\n"
            "**Owner:** Backend\n\n"
            "**Description**\n"
            "Implement the workflow with validation and persistence.\n\n"
            "**Inputs**\n- Plan API contract and harness test.\n\n"
            "**Outputs**\n- Endpoint and passing harness test.\n\n"
            "**Steps**\n1. Create the service and route from the plan contract.\n\n"
            "**Acceptance Criteria**\n1. `pytest -q` passes.\n\n"
            "**Rollback / Recovery**\nPure code change; revert if needed.\n\n"
            f"**Dependencies:** {dependencies}\n"
        )

    overview = "\n\n".join(
        [
            (
                "## Effort Summary\n"
                "- Estimate range: ~1 week\n"
                "- Tasks: 2 total - 2 MUST - 0 SHOULD - 0 COULD\n"
                "- Sizes: 2xM\n"
                "- Minimum cut: Ship MUST-only -> ~2d"
            ),
            "## Execution Overview\nDetailed implementation order with sequencing.",
            (
                "## Traceability Overview\n"
                "| Source ID | Plan section | Harness tests | Task IDs | "
                "Completion evidence |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | API Design | test_create_project | T-001 | pytest passes |"
            ),
            "## Dependency Graph\n```mermaid\ngraph TD\n  T001\n  T002\n```",
            "## Task Sizing Legend\nM means one to three days with focused tests.",
        ]
    )
    return (
        f"{overview}\n\n## Phase 1: API Layer\n\n"
        f"{_block(1, 'Implement Project Creation', first_dependencies)}\n"
        f"{_block(2, 'Implement Project Listing', second_dependencies)}"
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


# ---------------------------------------------------------------------------
# F7 (scalability audit P2): async validator parity. The offloaded validators
# must pass and raise exactly like the sync ones — including through the
# dedicated CPU pool (min_chars=0 forces the dispatch path).
# ---------------------------------------------------------------------------


async def test_validate_sections_async_passes_when_all_present(monkeypatch) -> None:
    from config import settings
    from services.pipeline.artifact_validator import validate_sections_async

    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    await validate_sections_async("plan", _complete_plan_artifact(), {})


async def test_validate_sections_async_raises_identically(monkeypatch) -> None:
    from config import settings
    from services.pipeline.artifact_validator import validate_sections_async

    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    dropped = {"## Capacity Model", "## API Design"}
    artifact = "\n\n".join(
        f"{heading}\nbody\n"
        for heading in SECTION_CONTRACTS["plan"]
        if heading not in dropped
    )
    with pytest.raises(MissingSectionError) as excinfo:
        await validate_sections_async("plan", artifact, {})
    assert set(excinfo.value.missing) == dropped
    assert excinfo.value.stage_type == "plan"


async def test_validate_artifact_completeness_async_raises_identically(
    monkeypatch,
) -> None:
    from config import settings
    from services.pipeline.artifact_validator import (
        validate_artifact_completeness_async,
    )

    monkeypatch.setattr(settings, "cpu_offload_min_chars", 0)
    artifact = "\n\n".join(
        f"{heading}\nshallow\n" for heading in SECTION_CONTRACTS["spec"]
    )
    with pytest.raises(IncompleteArtifactError):
        await validate_artifact_completeness_async("spec", artifact, {})


# --------------------------------------------------------------------------- #
# Prompt-quality audit H1 — assembly-time duplicate-section guard
# --------------------------------------------------------------------------- #


def test_dedupe_contract_sections_drops_second_occurrence_keeps_first() -> None:
    from services.pipeline.artifact_validator import dedupe_contract_sections

    artifact = (
        "## Planning Summary\nsummary body\n\n"
        "## Data Model and Persistence\nFIRST data model\n\n"
        "## API Design\napi body\n\n"
        "## Data Model and Persistence\nSECOND conflicting data model\n\n"
        "## Observability and Audit Logging\nobservability body"
    )
    deduped, removed = dedupe_contract_sections("plan", artifact)
    assert removed == 1
    assert "FIRST data model" in deduped
    assert "SECOND conflicting data model" not in deduped
    assert deduped.count("## Data Model and Persistence") == 1
    # Neighbours are untouched.
    assert "api body" in deduped
    assert "observability body" in deduped


def test_dedupe_contract_sections_noop_without_duplicates() -> None:
    from services.pipeline.artifact_validator import dedupe_contract_sections

    artifact = _complete_plan_artifact()
    deduped, removed = dedupe_contract_sections("plan", artifact)
    assert removed == 0
    assert deduped == artifact


def test_dedupe_contract_sections_matches_decorated_duplicate() -> None:
    # A second emission decorated with the system prompt's parenthetical still
    # dedupes against the shorter contract heading (startswith semantics,
    # mirroring validate_sections' substring gate).
    from services.pipeline.artifact_validator import dedupe_contract_sections

    artifact = (
        "## Threat Model (STRIDE)\nFIRST threat model\n\n"
        "## Capacity Model\ncapacity body\n\n"
        "## Threat Model (STRIDE)\nSECOND threat model"
    )
    deduped, removed = dedupe_contract_sections("plan", artifact)
    assert removed == 1
    assert "FIRST threat model" in deduped
    assert "SECOND threat model" not in deduped


def test_dedupe_contract_sections_ignores_non_contract_headings() -> None:
    # Repeated ## Phase N headings are task-document structure, not contract
    # sections — the guard must never touch them.
    from services.pipeline.artifact_validator import dedupe_contract_sections

    artifact = (
        "## Effort Summary\ncounts\n\n"
        "## Phase 1: Foundations\n### T-001: Task one\nbody\n\n"
        "## Phase 1: Foundations\n### T-002: Task two\nbody"
    )
    deduped, removed = dedupe_contract_sections("tasks", artifact)
    assert removed == 0
    assert deduped == artifact


def test_dedupe_contract_sections_never_touches_files_region() -> None:
    # `## Files` is additive and has its own per-file self-heal; a duplicated
    # `## Files` heading must not cause the whole second region to be dropped.
    from services.pipeline.artifact_validator import dedupe_contract_sections

    artifact = (
        "## Harness Overview\noverview\n\n"
        "## Files\n### File: a_test.py\n```python\nassert True\n```\n\n"
        "## Files\n### File: b_test.py\n```python\nassert True\n```"
    )
    deduped, removed = dedupe_contract_sections("harness", artifact)
    assert removed == 0
    assert "b_test.py" in deduped


def test_dedupe_contract_sections_ignores_headings_inside_fences() -> None:
    from services.pipeline.artifact_validator import dedupe_contract_sections

    artifact = (
        "## API Design\napi body\n\n"
        "```markdown\n## API Design\n(fenced example, not a heading)\n```\n\n"
        "## Observability and Audit Logging\nobservability body"
    )
    deduped, removed = dedupe_contract_sections("plan", artifact)
    assert removed == 0
    assert deduped == artifact


def test_dedupe_contract_sections_drop_ends_at_next_heading() -> None:
    from services.pipeline.artifact_validator import dedupe_contract_sections

    artifact = (
        "## Acceptance Criteria\nAC-001 first\n\n"
        "## Edge Cases\nedge body\n\n"
        "## Acceptance Criteria\nAC-001 duplicate\n### sub-detail\nkept? no\n\n"
        "## Constraints\nconstraint body"
    )
    deduped, removed = dedupe_contract_sections("spec", artifact)
    assert removed == 1
    # The duplicate's H3 sub-content travels with the dropped section...
    assert "sub-detail" not in deduped
    # ...but the next contract section survives.
    assert "constraint body" in deduped


# --------------------------------------------------------------------------- #
# Prompt-quality audit M6 — assembly-time Effort Summary reconciliation
# --------------------------------------------------------------------------- #

_EFFORT_TASKS_DOC = (
    "## Effort Summary\n"
    "- `Estimate range: ~3w`\n"
    "- `Tasks: 40 total · 30 MUST · 8 SHOULD · 2 COULD`\n"
    "- `Sizes: 5xXL · 20xL · 10xM · 5xS`\n"
    "- `Minimum cut: Ship MUST-only → ~9d`\n\n"
    "## Execution Overview\noverview\n\n"
    "## Phase 1: Foundations\n\n"
    "### T-001: First task\n\n"
    "**Priority:** MUST\n"
    "**Estimate:** M\n\n"
    "### T-002: Second task\n\n"
    "**Priority:** SHOULD\n"
    "**Estimate:** S\n\n"
    "### T-003: Third task\n\n"
    "**Priority:** MUST\n"
    "**Estimate:** M\n"
)


def test_reconcile_effort_summary_rewrites_counts_from_blocks() -> None:
    from services.pipeline.artifact_validator import reconcile_effort_summary

    reconciled, changed = reconcile_effort_summary(_EFFORT_TASKS_DOC)
    assert changed is True
    assert "- `Tasks: 3 total · 2 MUST · 1 SHOULD · 0 COULD`" in reconciled
    assert "- `Sizes: 2xM · 1xS`" in reconciled
    # Judgment lines are never rewritten.
    assert "- `Estimate range: ~3w`" in reconciled
    assert "- `Minimum cut: Ship MUST-only → ~9d`" in reconciled


def test_reconcile_effort_summary_idempotent_when_counts_match() -> None:
    from services.pipeline.artifact_validator import reconcile_effort_summary

    reconciled, _ = reconcile_effort_summary(_EFFORT_TASKS_DOC)
    again, changed = reconcile_effort_summary(reconciled)
    assert changed is False
    assert again == reconciled


def test_reconcile_effort_summary_noop_without_section_or_tasks() -> None:
    from services.pipeline.artifact_validator import reconcile_effort_summary

    no_section = "### T-001: Task\n**Priority:** MUST\n**Estimate:** S\n"
    assert reconcile_effort_summary(no_section) == (no_section, False)

    no_tasks = "## Effort Summary\n- `Tasks: 4 total · 4 MUST · 0 SHOULD · 0 COULD`\n"
    assert reconcile_effort_summary(no_tasks) == (no_tasks, False)


def test_reconcile_effort_summary_noop_on_demo_day_format() -> None:
    # Demo Day's Effort Summary has neither a Tasks: nor a Sizes: line.
    from services.pipeline.artifact_validator import reconcile_effort_summary

    doc = (
        "## Effort Summary\n"
        "Estimated build time: ~4h (target ≤ 5h)\n\n"
        "## Tasks\n\n### T-001: Build the skeleton\n**Priority:** MUST\n"
    )
    assert reconcile_effort_summary(doc) == (doc, False)


def test_reconcile_effort_summary_keeps_forecast_when_fields_unparsable() -> None:
    # No valid Priority/Estimate anywhere: rewriting to zeros would be worse
    # than the model's forecast, so both count lines stay untouched.
    from services.pipeline.artifact_validator import reconcile_effort_summary

    doc = (
        "## Effort Summary\n"
        "- `Tasks: 2 total · 2 MUST · 0 SHOULD · 0 COULD`\n"
        "- `Sizes: 2xM`\n\n"
        "### T-001: A task\nno fields\n\n### T-002: Another\nno fields\n"
    )
    assert reconcile_effort_summary(doc) == (doc, False)


def test_reconcile_effort_summary_only_touches_effort_summary_section() -> None:
    from services.pipeline.artifact_validator import reconcile_effort_summary

    doc = (
        _EFFORT_TASKS_DOC
        + "\n## Notes\n- `Tasks: 99 total · 99 MUST · 0 SHOULD · 0 COULD`\n"
    )
    reconciled, changed = reconcile_effort_summary(doc)
    assert changed is True
    # The lookalike line outside ## Effort Summary is untouched.
    assert "- `Tasks: 99 total · 99 MUST · 0 SHOULD · 0 COULD`" in reconciled

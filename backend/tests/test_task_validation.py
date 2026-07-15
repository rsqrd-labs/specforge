from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from services.evals.online_eval import (
    _extract_dropped_categories,
    _extract_harness_refs,
    _parse_task_blocks,
    _ref_in_dropped_category,
    _ref_matches_harness,
    _validate_task_references,
    extract_deferred_reqs,
    persist_structural_eval,
    run_eval,
    validate_stage_findings,
)

_HARNESS = """\
## File: harness/tests/test_auth.py

```python
class TestAuth:
    def test_login_success(self):
        assert True

    def test_login_failure(self):
        assert True

def test_standalone():
    assert True
```

## File: harness/tests/test_billing.py

```python
def test_charge_card():
    assert True
```
"""

_HARNESS_TS = """\
### File: harness/tests/admin.test.ts

```ts
describe('admin api', () => {
  it('health_live_returns_200', async () => {
    expect(true).toBe(true)
  })

  it('delete_report_suppresses_delivery', async () => {
    expect(true).toBe(true)
  })
})
```

### File: harness/tests/schemas.test.ts

```typescript
describe('contract schemas', () => {
  test("admin_config_response_shape", async () => {
    expect(true).toBe(true)
  })
})
```
"""

_TASKS_TS = """\
### T-001: Implement health endpoint

**Phase:** API Layer
**Spec refs:** FR-001
**Harness refs:** `tests/admin.test.ts::health_live_returns_200`
**Priority:** MUST
**Estimate:** S
**Estimated size:** S
**Risk:** Low

### T-002: Implement admin config schema

**Phase:** API Layer
**Spec refs:** FR-002
**Harness refs:** `tests/schemas.test.ts::admin_config_response_shape`
**Priority:** MUST
**Estimate:** S
**Estimated size:** S
**Risk:** Low

### T-003: Delete report flow

**Phase:** API Layer
**Spec refs:** FR-003
**Harness refs:** `tests/admin.test.ts::admin api::delete_report_suppresses_delivery`
**Priority:** MUST
**Estimate:** M
**Estimated size:** M
**Risk:** Medium
"""

_TASKS = """\
## Phase 1: Core

### T-001: Implement login endpoint

**Phase:** Core
**Spec refs:** FR-001
**Plan refs:** Auth API
**Harness refs:** `tests/test_auth.py::TestAuth::test_login_success`,
  `tests/test_auth.py::TestAuth::test_login_failure`
**Priority:** MUST
**Estimate:** S
**Estimated size:** S
**Risk:** Low — simple endpoint

### T-002: Implement billing

**Phase:** Core
**Spec refs:** FR-010
**Plan refs:** Billing API
**Harness refs:** `tests/test_billing.py::test_charge_card`
**Priority:** MUST
**Estimate:** M
**Estimated size:** M
**Risk:** Medium — external service

### T-003: Set up CI pipeline

**Phase:** Infrastructure
**Spec refs:** NFR-001
**Plan refs:** CI config
**Harness refs:** _(none — setup-only: no harness test for CI configuration)_
**Priority:** SHOULD
**Estimate:** S
**Estimated size:** XS
**Risk:** Low
"""

_TASKS_MISSING_FIELD = """\
### T-001: Task with missing harness refs field

**Phase:** Core
**Spec refs:** FR-001
**Harness refs:** `tests/test_auth.py::TestAuth::test_login_success`

### T-002: Task with no harness refs field at all

**Phase:** Core
**Spec refs:** FR-002
**Estimated size:** S
"""

_TASKS_GENUINE_GAP = """\
### T-001: Task with unmatched ref

**Phase:** Core
**Spec refs:** FR-001
**Harness refs:** `tests/test_auth.py::TestAuth::test_nonexistent_method`
**Priority:** MUST
**Estimate:** S
**Estimated size:** S
"""

# Harness that populated auth but recorded performance_budget as deferred under
# its token budget (a TestCategoryGap Coverage Plan record).
_HARNESS_DROPPED = """\
## Coverage Plan

TestCategoryGap: category=performance_budget reason=token_budget reqs=FR-012

## File: harness/tests/test_auth.py

```python
def test_login_success():
    assert True
```
"""

# Every unmatched ref is in the deferred performance_budget category → deferred.
_TASKS_DEFERRED = """\
### T-001: Enforce source-to-run budget

**Phase:** Performance
**Spec refs:** FR-012
**Harness refs:** `tests/performance_budget.test.ts::budget_is_enforced`
**Priority:** MUST
**Estimate:** M
**Estimated size:** M
"""

# One genuine defect (missing auth test, a category the harness DID populate) plus
# one deferred ref → GENUINE_GAP must win; the real hole is never masked.
_TASKS_MIXED = """\
### T-001: Mixed refs

**Phase:** Core
**Spec refs:** FR-001
**Harness refs:** `tests/performance_budget.test.ts::budget_is_enforced`,
  `tests/test_auth.py::test_totally_missing`
**Priority:** MUST
**Estimate:** M
**Estimated size:** M
"""

# Genuinely-missing ref in a category the harness populated (NOT dropped) → must
# stay GENUINE_GAP even though a TestCategoryGap exists for a different category.
_TASKS_GENUINE_WITH_DROP = """\
### T-001: Missing auth test

**Phase:** Core
**Spec refs:** FR-001
**Harness refs:** `tests/test_auth.py::test_totally_missing`
**Priority:** MUST
**Estimate:** S
**Estimated size:** S
"""

_TASKS_FILE_LEVEL_REFS = """\
### T-001: Build onboarding walking skeleton

**Harness refs:** `tests/e2e/onboarding-smoke.spec.ts`, `playwright.config.ts`
**Priority:** MUST
**Estimate:** M

### T-002: Implement the start endpoint

**Harness refs:** `tests/integration/api.start-onboarding.spec.ts`,
  `tests/helpers/http.ts`
**Priority:** MUST
**Estimate:** L
"""

_HARNESS_FILE_LEVEL_REFS = """\
### File: playwright.config.ts

```ts
export default {};
```

### File: tests/e2e/onboarding-smoke.spec.ts

```ts
test("completes onboarding", () => {});
```

### File: tests/integration/api.start-onboarding.spec.ts

```ts
test("creates a session", () => {});
```

### File: tests/helpers/http.ts

```ts
export function makeRequest() {}
```
"""


class TestParseTaskBlocks:
    def test_extracts_task_titles_and_refs(self) -> None:
        blocks = _parse_task_blocks(_TASKS)
        assert len(blocks) == 3
        t1 = blocks[0]
        assert t1["task_number"] == 1
        assert t1["task_title"] == "Implement login endpoint"
        assert "tests/test_auth.py::TestAuth::test_login_success" in t1["harness_refs"]
        assert "tests/test_auth.py::TestAuth::test_login_failure" in t1["harness_refs"]

    def test_detects_missing_harness_refs_field(self) -> None:
        blocks = _parse_task_blocks(_TASKS_MISSING_FIELD)
        assert blocks[0]["harness_refs"] is not None  # has field
        assert blocks[1]["harness_refs"] is None  # missing field → GENERATION_FAILURE

    def test_handles_setup_only_tasks(self) -> None:
        blocks = _parse_task_blocks(_TASKS)
        t3 = blocks[2]
        assert t3["task_number"] == 3
        assert t3["harness_refs"] == []  # setup-only — not None, not refs

    def test_empty_tasks_returns_empty_list(self) -> None:
        assert _parse_task_blocks("") == []
        assert _parse_task_blocks("# Just a heading, no tasks") == []


class TestExtractHarnessRefs:
    def test_finds_top_level_test_functions(self) -> None:
        known = _extract_harness_refs(_HARNESS)
        assert "test_standalone" in known
        assert "tests/test_auth.py::test_standalone" in known

    def test_finds_class_method_variants(self) -> None:
        known = _extract_harness_refs(_HARNESS)
        assert "TestAuth::test_login_success" in known
        assert "tests/test_auth.py::TestAuth::test_login_success" in known
        assert "test_login_success" in known

    def test_strips_harness_prefix_from_file_paths(self) -> None:
        known = _extract_harness_refs(_HARNESS)
        assert "harness/tests/test_auth.py::test_standalone" not in known
        assert "tests/test_auth.py::test_standalone" in known

    def test_indexes_whole_file_references(self) -> None:
        known = _extract_harness_refs(_HARNESS_FILE_LEVEL_REFS)
        assert "tests/e2e/onboarding-smoke.spec.ts" in known
        assert "playwright.config.ts" in known
        assert "tests/helpers/http.ts" in known

    def test_empty_harness_returns_empty_set(self) -> None:
        assert _extract_harness_refs("") == set()

    def test_harness_without_code_blocks_still_indexes_file(self) -> None:
        assert _extract_harness_refs("## File: tests/test_x.py\n\nNo code block.") == {
            "tests/test_x.py"
        }

    def test_finds_typescript_it_and_test_blocks(self) -> None:
        # TS/JS runners (Vitest/Jest) use it()/test()/describe(); TASKS
        # references these names verbatim, so they must be extracted or every
        # TS-test reference false-positives as a coverage gap (issue: 18 gaps).
        known = _extract_harness_refs(_HARNESS_TS)
        assert "health_live_returns_200" in known
        assert "tests/admin.test.ts::health_live_returns_200" in known
        # test() form, double-quoted name
        assert "admin_config_response_shape" in known

    def test_finds_typescript_describe_qualified_variants(self) -> None:
        known = _extract_harness_refs(_HARNESS_TS)
        assert "admin api::delete_report_suppresses_delivery" in known


class TestRefMatchesHarness:
    def setup_method(self) -> None:
        self.known = _extract_harness_refs(_HARNESS)

    def test_exact_path_match(self) -> None:
        assert _ref_matches_harness(
            "tests/test_auth.py::TestAuth::test_login_success", self.known
        )

    def test_strips_harness_prefix(self) -> None:
        assert _ref_matches_harness(
            "harness/tests/test_auth.py::TestAuth::test_login_success", self.known
        )

    def test_class_method_shorthand(self) -> None:
        assert _ref_matches_harness("TestAuth::test_login_success", self.known)

    def test_bare_function_name(self) -> None:
        assert _ref_matches_harness("test_standalone", self.known)

    def test_whole_file_reference(self) -> None:
        assert _ref_matches_harness("tests/test_auth.py", self.known)
        assert _ref_matches_harness("harness/tests/test_auth.py", self.known)

    def test_ignores_whitespace_around_reference_delimiter(self) -> None:
        assert _ref_matches_harness(
            "tests/test_auth.py :: TestAuth :: test_login_success", self.known
        )

    def test_nonexistent_ref_returns_false(self) -> None:
        assert not _ref_matches_harness(
            "tests/test_auth.py::TestAuth::test_bogus", self.known
        )
        assert not _ref_matches_harness("test_does_not_exist", self.known)


class TestValidateTaskReferences:
    def test_returns_empty_for_all_valid_refs(self) -> None:
        issues = _validate_task_references(_TASKS, _HARNESS)
        genuine_gaps = [i for i in issues if i["gap_type"] == "GENUINE_GAP"]
        assert genuine_gaps == []

    def test_setup_only_tasks_are_not_flagged(self) -> None:
        issues = _validate_task_references(_TASKS, _HARNESS)
        assert not any(i["task_number"] == 3 for i in issues)

    def test_typescript_refs_produce_no_false_gaps(self) -> None:
        # Regression: a full-stack generation whose harness ships TS tests must
        # not flag every TS-referencing task as a GENUINE_GAP (the 18-gap bug).
        issues = _validate_task_references(_TASKS_TS, _HARNESS_TS)
        genuine_gaps = [i for i in issues if i["gap_type"] == "GENUINE_GAP"]
        assert genuine_gaps == []

    def test_file_level_refs_produce_no_false_gaps(self) -> None:
        # Real generated tasks commonly own a whole test/config/helper file.
        # The file heading itself is sufficient traceability; requiring an
        # individual test name manufactured one false gap per task.
        issues = _validate_task_references(
            _TASKS_FILE_LEVEL_REFS, _HARNESS_FILE_LEVEL_REFS
        )
        assert issues == []

    def test_genuine_gap_for_unmatched_ref(self) -> None:
        issues = _validate_task_references(_TASKS_GENUINE_GAP, _HARNESS)
        assert len(issues) == 1
        issue = issues[0]
        assert issue["gap_type"] == "GENUINE_GAP"
        assert issue["task_number"] == 1
        assert "test_nonexistent_method" in issue["reason"]
        assert issue["remediation"] is not None
        assert "test_nonexistent_method" in issue["remediation"]

    def test_generation_failure_for_missing_field(self) -> None:
        issues = _validate_task_references(_TASKS_MISSING_FIELD, _HARNESS)
        failures = [i for i in issues if i["gap_type"] == "GENERATION_FAILURE"]
        assert len(failures) == 1
        assert failures[0]["task_number"] == 2

    def test_remediation_includes_file_path_hint_when_available(self) -> None:
        tasks = (
            "### T-001: Task\n\n**Harness refs:** "
            "`tests/auth/test_login.py::TestLogin::test_missing`\n"
        )
        issues = _validate_task_references(tasks, _HARNESS)
        assert issues[0]["gap_type"] == "GENUINE_GAP"
        assert "tests/auth/test_login.py" in issues[0]["remediation"]

    def test_remediation_uses_generic_hint_for_bare_function_refs(self) -> None:
        tasks = "### T-001: Task\n\n**Harness refs:** `test_nonexistent`\n"
        issues = _validate_task_references(tasks, _HARNESS)
        assert issues[0]["gap_type"] == "GENUINE_GAP"
        assert "test_nonexistent" in issues[0]["remediation"]

    def test_missing_file_ref_has_file_remediation_not_invalid_code_stub(self) -> None:
        tasks = (
            "### T-001: Task\n\n"
            "**Harness refs:** `tests/e2e/missing.spec.ts`\n"
            "**Priority:** MUST\n"
            "**Estimate:** S\n"
        )
        issues = _validate_task_references(tasks, _HARNESS_FILE_LEVEL_REFS)
        assert len(issues) == 1
        assert issues[0]["gap_type"] == "GENUINE_GAP"
        assert issues[0]["harness_file"] == "harness/tests/e2e/missing.spec.ts"
        assert issues[0]["code_stub"] is None
        assert issues[0]["remediation"] == (
            "Add the missing harness file `harness/tests/e2e/missing.spec.ts`."
        )

    def test_missing_root_config_ref_also_has_file_remediation(self) -> None:
        tasks = (
            "### T-001: Task\n\n"
            "**Harness refs:** `missing.config.ts`\n"
            "**Priority:** MUST\n"
            "**Estimate:** S\n"
        )
        issues = _validate_task_references(tasks, _HARNESS_FILE_LEVEL_REFS)
        assert len(issues) == 1
        assert issues[0]["harness_file"] == "harness/missing.config.ts"
        assert issues[0]["code_stub"] is None


class TestDroppedCategoryExtraction:
    def test_extracts_test_category_gap_records(self) -> None:
        cats = _extract_dropped_categories(_HARNESS_DROPPED)
        assert "performancebudget" in cats

    def test_no_records_returns_empty(self) -> None:
        assert _extract_dropped_categories(_HARNESS) == set()

    def test_ref_in_dropped_category_matches_file_stem(self) -> None:
        cats = {"performancebudget"}
        ref = "tests/performance_budget.test.ts::budget_is_enforced"
        assert _ref_in_dropped_category(ref, cats) is True

    def test_ref_not_in_dropped_category_when_file_differs(self) -> None:
        cats = {"performancebudget"}
        # The category word appears only in the method name, not the file — must
        # NOT match (method-name coincidence is the over-masking trap).
        ref = "tests/test_auth.py::performance_budget_check"
        assert _ref_in_dropped_category(ref, cats) is False

    def test_ref_in_dropped_category_empty_set_is_false(self) -> None:
        ref = "tests/performance_budget.test.ts::budget_is_enforced"
        assert _ref_in_dropped_category(ref, set()) is False


class TestExtractDeferredReqs:
    """``extract_deferred_reqs`` reports genuine coverage holes (matrix→file).

    A requirement is a gap only when its matrix-mapped test file(s) were never
    emitted in ``## Files``. A requirement that maps to *some* emitted file — even
    if another of its tiers was trimmed — is covered, not a gap. This mirrors the
    real AWS-CUR harness, where the perf file was promised but never emitted
    (NFR-001/NFR-002 = real gaps) while the accessibility file was emitted
    (FR-006/NFR-005/AC-012 = covered, despite a TestCategoryGap depth record).
    """

    _HARNESS = (
        "## Requirement-to-Test Matrix\n"
        "| Source ID | behaviour | test file | test name |\n"
        "|---|---|---|---|\n"
        "| FR-002 | run starts | `tests/integration/ingest.test.ts` | starts |\n"
        "| FR-002 | run promptly | `tests/performance/perf.test.ts` | budget |\n"
        "| NFR-001 | p95 start | `tests/performance/perf.test.ts` | budget |\n"
        "| NFR-002 | p95 e2e | `tests/performance/perf.test.ts` | e2e_budget |\n"
        "| AC-012 | pdf a11y | `tests/accessibility/a11y.test.ts` | structure |\n"
        "| `GET /v1/x` | endpoint | `tests/contract/schemas.test.ts` | shape |\n\n"
        "## Coverage Plan\n"
        "**TestCategoryGap: category=accessibility reason=token_budget "
        "reqs=AC-012**\n\n"
        "## Files\n"
        "### File: harness/tests/integration/ingest.test.ts\n"
        "```ts\nit('starts', () => {});\n```\n"
        "### File: harness/tests/accessibility/a11y.test.ts\n"
        "```ts\nit('structure', () => {});\n```\n"
        "### File: harness/tests/contract/schemas.test.ts\n"
        "```ts\nit('shape', () => {});\n```\n"
    )

    def test_reports_only_genuine_holes(self) -> None:
        # perf.test.ts was never emitted -> NFR-001/NFR-002 are real gaps.
        assert extract_deferred_reqs(self._HARNESS) == ["NFR-001", "NFR-002"]

    def test_requirement_with_one_emitted_file_is_covered(self) -> None:
        # FR-002 maps to both perf (absent) and ingest (emitted) -> covered.
        assert "FR-002" not in extract_deferred_reqs(self._HARNESS)

    def test_trimmed_but_emitted_tier_is_not_a_gap(self) -> None:
        # AC-012 has a TestCategoryGap record but its a11y file WAS emitted.
        assert "AC-012" not in extract_deferred_reqs(self._HARNESS)

    def test_non_requirement_rows_are_ignored(self) -> None:
        # The `GET /v1/x` endpoint row is not a requirement ID.
        assert extract_deferred_reqs(self._HARNESS) == ["NFR-001", "NFR-002"]

    def test_fully_emitted_harness_has_no_gaps(self) -> None:
        emitted = self._HARNESS.replace(
            "### File: harness/tests/integration/ingest.test.ts\n"
            "```ts\nit('starts', () => {});\n```\n",
            "### File: harness/tests/integration/ingest.test.ts\n"
            "```ts\nit('starts', () => {});\n```\n"
            "### File: harness/tests/performance/perf.test.ts\n"
            "```ts\nit('budget', () => {});\nit('e2e_budget', () => {});\n```\n",
        )
        assert extract_deferred_reqs(emitted) == []

    def test_no_matrix_or_empty_returns_empty(self) -> None:
        assert extract_deferred_reqs(_HARNESS) == []
        assert extract_deferred_reqs("") == []


def _ref_gaps(issues: list[dict]) -> list[dict]:
    """Only the traceability gaps (genuine + deferred), not field issues."""
    return [i for i in issues if i["gap_type"] in ("GENUINE_GAP", "DEFERRED_COVERAGE")]


class TestDeferredCoverageClassification:
    def test_deferred_when_all_unmatched_refs_in_dropped_category(self) -> None:
        issues = _validate_task_references(_TASKS_DEFERRED, _HARNESS_DROPPED)
        gaps = _ref_gaps(issues)
        assert len(gaps) == 1
        assert gaps[0]["gap_type"] == "DEFERRED_COVERAGE"
        assert "deferred" in gaps[0]["remediation"].lower()

    def test_deferred_coverage_does_not_flag(self) -> None:
        _tasks, flagged = validate_stage_findings(
            "tasks", _TASKS_DEFERRED, _HARNESS_DROPPED
        )
        assert flagged is False

    def test_genuine_wins_on_mixed_task(self) -> None:
        # over-masking guard (c): one genuine + one deferred unmatched ref must
        # report GENUINE_GAP, never mask the real hole as deferred.
        issues = _validate_task_references(_TASKS_MIXED, _HARNESS_DROPPED)
        gaps = _ref_gaps(issues)
        assert len(gaps) == 1
        assert gaps[0]["gap_type"] == "GENUINE_GAP"

    def test_genuine_gap_in_non_dropped_category_still_genuine(self) -> None:
        # over-masking guard (b): a real miss in a populated category stays
        # GENUINE even when a TestCategoryGap exists for another category.
        issues = _validate_task_references(_TASKS_GENUINE_WITH_DROP, _HARNESS_DROPPED)
        gaps = _ref_gaps(issues)
        assert len(gaps) == 1
        assert gaps[0]["gap_type"] == "GENUINE_GAP"
        _tasks, flagged = validate_stage_findings(
            "tasks", _TASKS_GENUINE_WITH_DROP, _HARNESS_DROPPED
        )
        assert flagged is True


@pytest.mark.asyncio
async def test_run_eval_tasks_uses_structural_parser_when_harness_provided() -> None:
    """When harness_content is given, structural parser overrides LLM tasks_without_ref."""  # noqa: E501
    from tests.test_online_eval import _FakeDB, _FakeJudge

    db = _FakeDB()
    # LLM says no issues, but structural parser will find a GENUINE_GAP
    judge_response = (
        '{"scores": {"requirements_coverage": 80, "specificity_testability": 75, '
        '"traceability": 70, "feasibility": 80, "clarity": 75}, '
        '"coverage_percent": null, "uncovered_reqs": [], '
        '"tasks_without_ref": [], "risks": []}'
    )
    tasks_with_broken_ref = (
        "### T-001: Implement login\n\n"
        "**Harness refs:** `tests/test_auth.py::TestAuth::test_does_not_exist`\n"
        "**Priority:** MUST\n"
        "**Estimate:** S\n"
    )

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(
            uuid4(),
            "tasks",
            tasks_with_broken_ref,
            "spec context",
            db,
            harness_content=_HARNESS,
        )

    assert result is not None
    assert result.flagged is True
    assert result.tasks_without_ref is not None
    assert len(result.tasks_without_ref) == 1
    assert result.tasks_without_ref[0]["gap_type"] == "GENUINE_GAP"


@pytest.mark.asyncio
async def test_run_eval_tasks_falls_back_to_llm_when_no_harness_content() -> None:
    """When harness_content is absent, LLM-derived tasks_without_ref is used."""
    from tests.test_online_eval import _FakeDB, _FakeJudge

    db = _FakeDB()
    judge_response = (
        '{"overall_score": 70, "completeness": 75, "clarity": 80, '
        '"tasks_without_ref": [{"task": "T-01", "reason": "no test ref"}]}'
    )

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(uuid4(), "tasks", "tasks content", "spec", db)

    assert result is not None
    assert result.flagged is True
    assert len(result.tasks_without_ref) == 1


@pytest.mark.asyncio
async def test_run_eval_tasks_generation_failure_does_not_flag() -> None:
    """GENERATION_FAILURE issues are tracked but do not set flagged=True."""
    from tests.test_online_eval import _FakeDB, _FakeJudge

    db = _FakeDB()
    judge_response = (
        '{"scores": {"requirements_coverage": 80, "specificity_testability": 75, '
        '"traceability": 70, "feasibility": 80, "clarity": 75}, '
        '"coverage_percent": null, "uncovered_reqs": [], '
        '"tasks_without_ref": [], "risks": []}'
    )
    # Task with no **Harness refs:** field — GENERATION_FAILURE.
    # Priority/Estimate present so the T-164 field validators don't fire and
    # this test stays focused on the GENERATION_FAILURE-doesn't-flag behaviour.
    tasks_missing_field = (
        "### T-001: Task without harness refs field\n\n"
        "**Spec refs:** FR-001\n"
        "**Priority:** MUST\n"
        "**Estimate:** S\n"
        "**Estimated size:** S\n"
    )

    with patch(
        "services.evals.online_eval.get_llm", return_value=_FakeJudge(judge_response)
    ):
        result = await run_eval(
            uuid4(),
            "tasks",
            tasks_missing_field,
            "spec context",
            db,
            harness_content=_HARNESS,
        )

    assert result is not None
    assert result.flagged is False  # GENERATION_FAILURE doesn't surface to user
    assert result.tasks_without_ref is not None
    assert result.tasks_without_ref[0]["gap_type"] == "GENERATION_FAILURE"


# ---------------------------------------------------------------------------
# issue #27 Phase 1: validate_stage_findings — the deterministic, no-LLM helper
# shared by the generation flow and POST /stages/{id}/revalidate-tasks.
# ---------------------------------------------------------------------------


class TestValidateStageFindings:
    def test_tasks_with_harness_finds_genuine_gap_and_flags(self) -> None:
        tasks_without_ref, flagged = validate_stage_findings(
            "tasks", _TASKS_GENUINE_GAP, _HARNESS
        )
        assert tasks_without_ref is not None
        assert any(i["gap_type"] == "GENUINE_GAP" for i in tasks_without_ref)
        assert flagged is True

    def test_clean_tasks_against_harness_not_flagged(self) -> None:
        tasks_without_ref, flagged = validate_stage_findings("tasks", _TASKS, _HARNESS)
        assert tasks_without_ref == []
        assert flagged is False

    def test_generation_failure_does_not_flag(self) -> None:
        tasks_without_ref, flagged = validate_stage_findings(
            "tasks", _TASKS_MISSING_FIELD, _HARNESS
        )
        assert tasks_without_ref is not None
        assert any(i["gap_type"] == "GENERATION_FAILURE" for i in tasks_without_ref)
        # A GENERATION_FAILURE is a prompt-quality issue, never a user-facing flag.
        assert all(
            i["gap_type"] != "GENERATION_FAILURE"
            for i in tasks_without_ref
            if i["gap_type"] == "GENUINE_GAP"
        )

    def test_non_tasks_stage_returns_none(self) -> None:
        # Harness coverage flagging is LLM-derived and stays in _persist_eval_data.
        assert validate_stage_findings("harness", "content", "harness") == (None, False)
        assert validate_stage_findings("spec", "content", None) == (None, False)
        assert validate_stage_findings("plan", "content", "spec") == (None, False)

    def test_tasks_without_harness_returns_none(self) -> None:
        assert validate_stage_findings("tasks", _TASKS, None) == (None, False)
        assert validate_stage_findings("tasks", _TASKS, "") == (None, False)


@pytest.mark.asyncio
async def test_persist_structural_eval_persists_findings_with_null_score() -> None:
    """The inline persist writes deterministic findings and no score — no judge."""
    from tests.test_online_eval import _FakeDB

    db = _FakeDB()
    result = await persist_structural_eval(
        db,
        stage_version_id=uuid4(),
        stage_type="tasks",
        content=_TASKS_GENUINE_GAP,
        harness_content=_HARNESS,
    )

    assert result.overall_score is None
    assert result.completeness is None
    assert result.clarity is None
    assert result.coverage_percent is None
    assert result.flagged is True
    assert result.tasks_without_ref is not None
    assert any(i["gap_type"] == "GENUINE_GAP" for i in result.tasks_without_ref)
    assert db._committed


@pytest.mark.asyncio
async def test_persist_structural_eval_non_tasks_has_no_findings() -> None:
    from tests.test_online_eval import _FakeDB

    db = _FakeDB()
    result = await persist_structural_eval(
        db,
        stage_version_id=uuid4(),
        stage_type="spec",
        content="a spec body",
        harness_content=None,
    )

    assert result.overall_score is None
    assert result.tasks_without_ref is None
    assert result.flagged is False

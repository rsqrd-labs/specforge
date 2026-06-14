from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from services.evals.online_eval import (
    _extract_harness_refs,
    _parse_task_blocks,
    _ref_matches_harness,
    _validate_task_references,
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

    def test_empty_harness_returns_empty_set(self) -> None:
        assert _extract_harness_refs("") == set()

    def test_harness_without_code_blocks_returns_empty_set(self) -> None:
        assert (
            _extract_harness_refs("## File: tests/test_x.py\n\nNo code block.") == set()
        )


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

"""Demo Day mode — Phase 3 (construction verifier) tests.

The linter is zero-LLM and joins on the exact tokens the Demo Day prompts
(``backend/prompts/demo_day.py``) emit, so these fixtures are written in that
literal token shape. A golden VERIFIED package proves the happy path; one
mutator per check proves each gap is caught and named.
"""

from __future__ import annotations

from services.pipeline import agent_manual_service
from services.pipeline.demo_day_plan_linter import (
    DEMO_DAY_DEFAULT_BUDGET_MINUTES,
    ConstructionVerdict,
    verify_construction,
)

# ---------------------------------------------------------------------------
# A golden, internally-consistent Demo Day package (all of C1–C4 pass).
# ---------------------------------------------------------------------------

_SPEC = """# SPEC

## Overview

A tiny URL shortener demo.

## Acceptance Criteria

- AC-001: POST /shorten returns a short code for a valid URL.
- AC-002: GET /{code} redirects to the original URL.
- AC-003: The smoke journey (shorten then resolve) works end to end.
"""

_HARNESS = """# HARNESS

## Harness Overview

Run `pytest` from the repo root. SQLite, no provisioning.

## Frozen Interface Contracts

POST /shorten -> {code}. GET /{code} -> 302.

## Requirement-to-Test Matrix

| ID | Behaviour | Test file | Test name | Type |
| --- | --- | --- | --- | --- |
| AC-001 | shorten | `tests/test_shorten.py` | test_shorten | unit |
| AC-002 | resolve | `tests/test_resolve.py` | test_resolve | unit |
| AC-003 | journey | `tests/e2e/test_smoke.py` | test_smoke | e2e |

## End-to-End Smoke Test

The unmockable test `tests/e2e/test_smoke.py` drives shorten-then-resolve and is
green from the first slice.

## File Tree

```
tests/test_shorten.py
tests/test_resolve.py
tests/e2e/test_smoke.py
app/main.py
```

## Files

### File: tests/e2e/test_smoke.py

```python
def test_smoke():
    assert True
```

### File: tests/test_shorten.py

```python
def test_shorten():
    assert True
```

### File: tests/test_resolve.py

```python
def test_resolve():
    assert True
```
"""

_TASK_TEMPLATE = """### {tid}: {title}

**Spec refs:** {spec_refs}
**Plan refs:** Interface Contracts
**Harness refs:** {harness_refs}
**Priority:** MUST
**Estimate:** M
**Estimated minutes:** {minutes}
**Precondition:** {precondition}

**Steps**
1. Implement {title}.

**Acceptance Criteria**
1. `pytest {harness_refs}`
"""


def _task(tid, title, spec_refs, harness_refs, minutes, precondition):
    return _TASK_TEMPLATE.format(
        tid=tid,
        title=title,
        spec_refs=spec_refs,
        harness_refs=harness_refs,
        minutes=minutes,
        precondition=precondition,
    )


def _tasks_doc(blocks):
    return (
        "# TASKS\n\n"
        "## Effort Summary\n\n"
        "Estimated build time: ~4h (target ≤ 5h). Advisory.\n\n"
        "## Build Order\n\n"
        "T-001 then T-002 then T-003 then T-004; app green after each.\n\n"
        "## Traceability Overview\n\n"
        "AC-001 -> tests/test_shorten.py -> T-002; "
        "AC-002 -> tests/test_resolve.py -> T-003; "
        "AC-003 -> tests/e2e/test_smoke.py -> T-001, T-004.\n\n"
        "## Tasks\n\n" + "\n".join(blocks)
    )


def _verified_tasks():
    return _tasks_doc(
        [
            _task(
                "T-001",
                "Walking skeleton",
                "FR-001, AC-003",
                "`tests/e2e/test_smoke.py`",
                60,
                "none",
            ),
            _task(
                "T-002",
                "Shorten endpoint",
                "FR-002, AC-001",
                "`tests/test_shorten.py`",
                60,
                "T-001",
            ),
            _task(
                "T-003",
                "Resolve endpoint",
                "FR-003, AC-002",
                "`tests/test_resolve.py`",
                60,
                "T-001, T-002",
            ),
            _task(
                "T-004",
                "Final smoke pass",
                "AC-003",
                "`tests/e2e/test_smoke.py`",
                45,
                "T-001, T-002, T-003",
            ),
        ]
    )


def _verify(spec=_SPEC, harness=_HARNESS, tasks=None, **kwargs):
    return verify_construction(
        spec=spec,
        plan="# PLAN",
        harness=harness,
        tasks=tasks if tasks is not None else _verified_tasks(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Golden VERIFIED.
# ---------------------------------------------------------------------------


def test_golden_package_is_verified():
    verdict = _verify(stage_versions={"spec": 1, "plan": 1, "harness": 1, "tasks": 1})
    assert verdict.verified is True
    assert all(verdict.checks[c].passed for c in ("C1", "C2", "C3", "C4"))
    assert verdict.estimated_minutes == 225
    assert verdict.time_budget_minutes == DEMO_DAY_DEFAULT_BUDGET_MINUTES
    assert verdict.stage_versions == {"spec": 1, "plan": 1, "harness": 1, "tasks": 1}
    assert verdict.regen_attempted is False


def test_verdict_to_dict_shape_round_trips_into_report():
    verdict = _verify()
    payload = verdict.to_dict()
    assert set(payload) == {
        "verified",
        "checks",
        "estimated_minutes",
        "time_budget_minutes",
        "stage_versions",
        "regen_attempted",
    }
    assert payload["checks"]["C1"] == {
        "name": "dag_acyclic",
        "passed": True,
        "gaps": [],
    }
    # The Phase 2 renderer consumes exactly this shape and must not raise.
    report = agent_manual_service.build_construction_report(payload)
    assert "Construction-verified" in report


# ---------------------------------------------------------------------------
# One mutator per check.
# ---------------------------------------------------------------------------


def test_c1_forward_precondition_fails_dag():
    # T-002 depends on T-003, which appears later — would break acyclicity.
    tasks = _tasks_doc(
        [
            _task(
                "T-001", "Skeleton", "AC-003", "`tests/e2e/test_smoke.py`", 60, "none"
            ),
            _task("T-002", "Shorten", "AC-001", "`tests/test_shorten.py`", 60, "T-003"),
            _task("T-003", "Resolve", "AC-002", "`tests/test_resolve.py`", 60, "T-001"),
            _task("T-004", "Smoke", "AC-003", "`tests/e2e/test_smoke.py`", 45, "T-001"),
        ]
    )
    verdict = _verify(tasks=tasks)
    assert verdict.verified is False
    assert verdict.checks["C1"].passed is False
    assert any("T-003" in gap for gap in verdict.checks["C1"].gaps)


def test_c2_unknown_harness_ref_fails_task_to_test():
    tasks = _tasks_doc(
        [
            _task(
                "T-001", "Skeleton", "AC-003", "`tests/e2e/test_smoke.py`", 60, "none"
            ),
            _task("T-002", "Shorten", "AC-001", "`tests/test_ghost.py`", 60, "T-001"),
            _task("T-003", "Resolve", "AC-002", "`tests/test_resolve.py`", 60, "T-001"),
            _task("T-004", "Smoke", "AC-003", "`tests/e2e/test_smoke.py`", 45, "T-001"),
        ]
    )
    verdict = _verify(tasks=tasks)
    assert verdict.verified is False
    assert verdict.checks["C2"].passed is False
    assert any("test_ghost.py" in gap for gap in verdict.checks["C2"].gaps)


def test_c2_none_escape_is_exempt():
    tasks = _tasks_doc(
        [
            _task(
                "T-001", "Bootstrap", "FR-001", "_(none — scaffold only)_", 30, "none"
            ),
            _task("T-002", "Shorten", "AC-001", "`tests/test_shorten.py`", 60, "T-001"),
            _task("T-003", "Resolve", "AC-002", "`tests/test_resolve.py`", 60, "T-002"),
            _task("T-004", "Smoke", "AC-003", "`tests/e2e/test_smoke.py`", 45, "T-003"),
        ]
    )
    verdict = _verify(tasks=tasks)
    assert verdict.checks["C2"].passed is True


def test_c3_ac_missing_from_rtm_fails_ac_to_test():
    harness = _HARNESS.replace(
        "| AC-003 | journey | `tests/e2e/test_smoke.py` | test_smoke | e2e |\n", ""
    )
    verdict = _verify(harness=harness)
    assert verdict.verified is False
    assert verdict.checks["C3"].passed is False
    assert any("AC-003" in gap for gap in verdict.checks["C3"].gaps)


def test_c3_ac_not_referenced_by_task_fails():
    # Drop AC-002 everywhere in the tasks doc so it is in the RTM but no task.
    tasks = _verified_tasks().replace("AC-002", "AC-999")
    verdict = _verify(tasks=tasks)
    assert verdict.verified is False
    assert verdict.checks["C3"].passed is False
    assert any(
        "AC-002" in gap and "not referenced" in gap for gap in verdict.checks["C3"].gaps
    )


def test_c4_final_task_not_citing_e2e_fails():
    tasks = _tasks_doc(
        [
            _task(
                "T-001", "Skeleton", "AC-003", "`tests/e2e/test_smoke.py`", 60, "none"
            ),
            _task("T-002", "Shorten", "AC-001", "`tests/test_shorten.py`", 60, "T-001"),
            _task("T-003", "Resolve", "AC-002", "`tests/test_resolve.py`", 60, "T-002"),
            # Final task forgets to cite the e2e path.
            _task("T-004", "Polish", "AC-003", "`tests/test_resolve.py`", 45, "T-003"),
        ]
    )
    verdict = _verify(tasks=tasks)
    assert verdict.verified is False
    assert verdict.checks["C4"].passed is False
    assert any("test_smoke.py" in gap for gap in verdict.checks["C4"].gaps)


def test_c4_no_e2e_named_in_harness_fails():
    harness = _HARNESS.replace(
        "The unmockable test `tests/e2e/test_smoke.py` drives shorten-then-resolve"
        " and is\ngreen from the first slice.",
        "We run the suite and eyeball the result.",
    )
    verdict = _verify(harness=harness)
    assert verdict.checks["C4"].passed is False


# ---------------------------------------------------------------------------
# C5 is advisory — it never flips the verdict.
# ---------------------------------------------------------------------------


def test_c5_over_budget_does_not_flip_verdict():
    verdict = _verify(time_budget_minutes=60)  # 225 > 60
    assert verdict.verified is True  # C1–C4 still pass
    assert verdict.checks["C5"].passed is False
    assert verdict.estimated_minutes == 225
    assert verdict.time_budget_minutes == 60


def test_c5_no_estimates_yields_none():
    tasks = _verified_tasks().replace("**Estimated minutes:**", "**Est min:**")
    verdict = _verify(tasks=tasks)
    assert verdict.estimated_minutes is None
    assert verdict.checks["C5"].passed is True  # advisory, no data
    assert verdict.verified is True


def test_default_budget_applies_when_unset():
    verdict = _verify(time_budget_minutes=None)
    assert verdict.time_budget_minutes == DEMO_DAY_DEFAULT_BUDGET_MINUTES


def test_construction_verdict_is_dataclass_instance():
    assert isinstance(_verify(), ConstructionVerdict)

"""Unit tests for T-USE-05 — per-task Priority/Estimate structural validation.

These exercise `_validate_task_fields` directly and the wired
`_validate_task_references` path so the merged `tasks_without_ref` list
carries both flavours of structural issue without any UI shape change.
"""

from __future__ import annotations

from services.evals.online_eval import (
    _validate_task_fields,
    _validate_task_references,
)

_CLEAN = """\
### T-001: Implement user model

**Phase:** Data Layer
**Harness refs:** `tests/test_user.py::test_user`
**Priority:** MUST
**Estimate:** M

Description here.
"""

_MISSING_PRIORITY_ON_T002 = """\
### T-001: Implement user model

**Harness refs:** `tests/test_user.py::test_user`
**Priority:** MUST
**Estimate:** S

### T-002: Implement login endpoint

**Harness refs:** `tests/test_auth.py::test_login`
**Estimate:** M

Description.
"""

_INVALID_PRIORITY_ENUM = """\
### T-001: Implement user model

**Harness refs:** `tests/test_user.py::test_user`
**Priority:** CRITICAL
**Estimate:** L
"""

_MISSING_ESTIMATE = """\
### T-001: Implement user model

**Harness refs:** `tests/test_user.py::test_user`
**Priority:** SHOULD
"""

_HARNESS_DOC = """\
## File: tests/test_user.py

```python
def test_user():
    pass
```

## File: tests/test_auth.py

```python
def test_login():
    pass
```
"""


def test_validate_task_fields_returns_no_issues_for_clean_content() -> None:
    assert _validate_task_fields(_CLEAN) == []


def test_validate_task_fields_flags_missing_priority_on_t002() -> None:
    issues = _validate_task_fields(_MISSING_PRIORITY_ON_T002)
    priority_issues = [i for i in issues if i["gap_type"] == "MISSING_PRIORITY"]
    assert len(priority_issues) == 1
    assert priority_issues[0]["task_number"] == 2
    assert "Priority" in priority_issues[0]["reason"]
    assert priority_issues[0]["remediation"]
    # T-002 has Estimate so no MISSING_ESTIMATE for it; T-001 is clean.
    assert all(i["gap_type"] != "MISSING_ESTIMATE" for i in issues)


def test_validate_task_fields_flags_invalid_priority_enum_value() -> None:
    issues = _validate_task_fields(_INVALID_PRIORITY_ENUM)
    priority_issues = [i for i in issues if i["gap_type"] == "MISSING_PRIORITY"]
    assert len(priority_issues) == 1
    # Must mention the invalid value to be actionable.
    assert "CRITICAL" in priority_issues[0]["reason"]


def test_validate_task_fields_flags_missing_estimate() -> None:
    issues = _validate_task_fields(_MISSING_ESTIMATE)
    estimate_issues = [i for i in issues if i["gap_type"] == "MISSING_ESTIMATE"]
    assert len(estimate_issues) == 1
    assert estimate_issues[0]["task_number"] == 1


def test_validate_task_references_merges_field_issues_into_tasks_without_ref() -> None:
    # End-to-end: confirm the wired path emits MISSING_* issues alongside any
    # existing T-NNN harness-reference issues, so TaskValidationPanel surfaces both
    # without any UI shape change.
    issues = _validate_task_references(_MISSING_PRIORITY_ON_T002, _HARNESS_DOC)
    gap_types = {i["gap_type"] for i in issues}
    assert "MISSING_PRIORITY" in gap_types
    # Every harness ref is valid in this harness, so no GENUINE_GAP.
    assert "GENUINE_GAP" not in gap_types

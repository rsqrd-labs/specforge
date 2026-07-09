"""Grader unit tests — prompt_eval/graders/coverage.py.

Prompt Quality Remediation finding #8: a harness that recorded a
``TestCategoryGap`` had no defined tasks-stage acknowledgement behavior. These
pin the new deterministic grader that catches a regression of that fix without
needing a live model call.
"""

from __future__ import annotations

from prompt_eval.graders.coverage import (
    test_category_gap_acknowledged_in_tasks as gap_grader,
)

_HARNESS_NO_GAPS = """## Coverage Plan
No TestCategoryGap records are present.
"""

_HARNESS_ONE_GAP = """## Coverage Plan
TestCategoryGap: category=performance_budget reason=token_budget reqs=FR-012
"""

_HARNESS_TWO_GAPS = """## Coverage Plan
TestCategoryGap: category=performance_budget reason=token_budget reqs=FR-012
TestCategoryGap: category=accessibility reason=token_budget reqs=FR-014
"""


def test_not_applicable_for_non_tasks_stage() -> None:
    result = gap_grader(
        "harness", _HARNESS_ONE_GAP, {}
    )
    assert result.score == 1.0


def test_no_gap_records_scores_full_marks() -> None:
    result = gap_grader(
        "tasks", "# Tasks\n### T-001: Do a thing\n", {"harness": _HARNESS_NO_GAPS}
    )
    assert result.score == 1.0
    assert result.metadata["gap_categories"] == 0


def test_acknowledged_gap_scores_full_marks() -> None:
    tasks_md = (
        "## Assumptions and Open Questions\n"
        "- performance_budget coverage was deferred by the harness under token "
        "budget for FR-012; revisit before launch.\n"
    )
    result = gap_grader(
        "tasks", tasks_md, {"harness": _HARNESS_ONE_GAP}
    )
    assert result.score == 1.0
    assert result.findings == ()


def test_unacknowledged_gap_scores_zero_with_finding() -> None:
    tasks_md = "# Tasks\n### T-001: Implement login\n"
    result = gap_grader(
        "tasks", tasks_md, {"harness": _HARNESS_ONE_GAP}
    )
    assert result.score == 0.0
    assert result.findings
    assert "performance_budget" in result.findings[0]


def test_partial_acknowledgement_of_multiple_gaps_scores_proportionally() -> None:
    tasks_md = (
        "## Assumptions and Open Questions\n"
        "- performance_budget coverage deferred (FR-012).\n"
    )
    result = gap_grader(
        "tasks", tasks_md, {"harness": _HARNESS_TWO_GAPS}
    )
    assert result.score == 0.5
    assert any("accessibility" in finding for finding in result.findings)

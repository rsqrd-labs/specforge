"""T-249 / directive #8 — deprecation-denylist freshness grader tests.

The pure freshness decision is tested with fixed dates so these tests are
deterministic and never become a time bomb.  The live grader's time-sensitive
behaviour (failing once the committed DENYLIST_LAST_REVIEWED is > 12 months
old) is the prompt-eval gate itself, not asserted here.
"""

from __future__ import annotations

import datetime

from prompt_eval.graders.quality import (
    _freshness_deadline,
    _read_denylist_review_date,
    _score_denylist_freshness,
    denylist_freshness,
)


def test_fresh_within_budget_scores_one() -> None:
    reviewed = datetime.date(2026, 1, 1)
    score, findings = _score_denylist_freshness(reviewed, datetime.date(2026, 6, 1))
    assert score == 1.0
    assert findings == []


def test_exactly_twelve_months_is_still_fresh() -> None:
    reviewed = datetime.date(2026, 5, 30)
    # The 12-month anniversary itself is within budget ("more than 12 months").
    score, _ = _score_denylist_freshness(reviewed, datetime.date(2027, 5, 30))
    assert score == 1.0


def test_one_day_past_twelve_months_is_stale() -> None:
    reviewed = datetime.date(2026, 5, 30)
    score, findings = _score_denylist_freshness(reviewed, datetime.date(2027, 5, 31))
    assert score == 0.0
    assert findings and "freshness budget" in findings[0]


def test_clearly_stale_scores_zero() -> None:
    reviewed = datetime.date(2024, 1, 1)
    score, findings = _score_denylist_freshness(reviewed, datetime.date(2026, 6, 1))
    assert score == 0.0
    assert findings and "Re-review the denylist" in findings[0]


def test_missing_anchor_fails_closed() -> None:
    score, findings = _score_denylist_freshness(None, datetime.date(2026, 6, 1))
    assert score == 0.0
    assert findings and "DENYLIST_LAST_REVIEWED not" in findings[0]


def test_leap_day_review_deadline_clamps_to_feb_28() -> None:
    # 2024-02-29 + 12 months has no Feb 29 in 2025 → clamp to Feb 28.
    assert _freshness_deadline(datetime.date(2024, 2, 29)) == datetime.date(2025, 2, 28)


def test_reads_committed_review_date_from_plan_py() -> None:
    reviewed = _read_denylist_review_date()
    assert isinstance(reviewed, datetime.date)


def test_grader_returns_well_formed_quality_result() -> None:
    result = denylist_freshness("plan", "", {})
    assert result.name == "denylist_freshness"
    assert result.axis == "quality"
    assert result.score in (0.0, 1.0)
    assert "last_reviewed" in result.metadata

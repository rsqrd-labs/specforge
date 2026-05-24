"""Unit tests for services/coverage_utils.py — T-198 (HF-1) batch N+1 fix.

Tests verify:
  CU-1  derive_coverage_summaries([]) returns {} without issuing a query
  CU-2  derive_coverage_summaries([id1, id2]) issues exactly ONE SQL query
  CU-3  derive_coverage_summaries returns None for workspaces with no eval
  CU-4  derive_coverage_summaries returns correct CoverageSummary values
  CU-5  derive_coverage_summaries clamps pct to [0, 100]
  CU-6  derive_coverage_summaries keeps only the most-recent eval per workspace
  CU-7  derive_coverage_summaries caps the batch to _MAX_BATCH_SIZE workspace IDs
  CU-8  derive_coverage_summary(single) delegates to the batch function
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from schemas.workspace import CoverageSummary
from services.coverage_utils import (
    _MAX_BATCH_SIZE,
    derive_coverage_summaries,
    derive_coverage_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(rows: list[tuple]) -> AsyncMock:
    """Return an AsyncSession mock whose execute() returns the given rows."""
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(rows))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ---------------------------------------------------------------------------
# CU-1: empty list short-circuits — no DB query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_list_returns_empty_dict_without_query() -> None:
    """CU-1 — derive_coverage_summaries([]) must return {} and issue no query."""
    db = AsyncMock()
    result = await derive_coverage_summaries([], db)

    assert result == {}, "Expected empty dict for empty workspace_ids list."
    db.execute.assert_not_called(), (
        "derive_coverage_summaries([]) must not issue any SQL query."
    )


# ---------------------------------------------------------------------------
# CU-2: single SQL query for multiple workspaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_issues_single_query() -> None:
    """CU-2 — derive_coverage_summaries must call db.execute exactly once."""
    id1, id2, id3 = uuid4(), uuid4(), uuid4()
    db = _make_db([(id1, 85), (id2, 60)])

    await derive_coverage_summaries([id1, id2, id3], db)

    assert db.execute.call_count == 1, (
        "derive_coverage_summaries must issue exactly 1 SQL query regardless of "
        f"workspace count. Got {db.execute.call_count} calls."
    )


# ---------------------------------------------------------------------------
# CU-3: None for workspaces with no eval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_for_workspace_with_no_eval() -> None:
    """CU-3 — workspaces with no matching eval rows must map to None."""
    id1, id2 = uuid4(), uuid4()
    # Only id1 has a result; id2 has none.
    db = _make_db([(id1, 75)])

    result = await derive_coverage_summaries([id1, id2], db)

    assert (
        result[id2] is None
    ), "Workspace with no eval result must map to None in the output dict."
    assert result[id1] is not None


# ---------------------------------------------------------------------------
# CU-4: correct CoverageSummary values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_coverage_summary_values() -> None:
    """CU-4 — CoverageSummary fields must reflect the DB coverage_percent."""
    wid = uuid4()
    db = _make_db([(wid, 73)])

    result = await derive_coverage_summaries([wid], db)

    summary = result[wid]
    assert isinstance(summary, CoverageSummary)
    assert summary.percent == 73
    assert summary.covered == 73
    assert summary.total == 100
    assert summary.tests == 0


# ---------------------------------------------------------------------------
# CU-5: clamp to [0, 100]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_percent_clamped_to_valid_range() -> None:
    """CU-5 — coverage_percent values outside [0, 100] must be clamped."""
    id_over, id_under = uuid4(), uuid4()
    db = _make_db([(id_over, 110), (id_under, -5)])

    result = await derive_coverage_summaries([id_over, id_under], db)

    assert result[id_over].percent == 100, "Values > 100 must be clamped to 100."
    assert result[id_under].percent == 0, "Values < 0 must be clamped to 0."


# ---------------------------------------------------------------------------
# CU-6: most-recent eval wins (first row in result set per workspace)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_most_recent_eval_wins() -> None:
    """CU-6 — only the first (most-recent) eval row per workspace is used.

    The query orders by created_at DESC, so the first row encountered for a
    workspace_id is the most recent.  Subsequent rows must be discarded.
    """
    wid = uuid4()
    # Simulate two rows for the same workspace: 80 first (most recent), 50 second.
    db = _make_db([(wid, 80), (wid, 50)])

    result = await derive_coverage_summaries([wid], db)

    assert result[wid].percent == 80, (
        "The most-recent eval row (first in DESC-ordered result) must win. "
        f"Got {result[wid].percent}."
    )


# ---------------------------------------------------------------------------
# CU-7: batch cap at _MAX_BATCH_SIZE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_size_cap_enforced() -> None:
    """CU-7 — workspace_ids exceeding _MAX_BATCH_SIZE are silently capped.

    The function must not raise; it just processes the first _MAX_BATCH_SIZE
    IDs and returns None for those beyond the cap.
    """
    # Generate more IDs than the cap.
    ids = [uuid4() for _ in range(_MAX_BATCH_SIZE + 10)]
    db = _make_db([])  # no coverage data — we just want to check no crash

    result = await derive_coverage_summaries(ids, db)

    # All requested IDs are present in the result dict (including the excess ones).
    assert len(result) == len(ids), (
        "All requested workspace IDs must appear in the result dict, even those "
        "beyond _MAX_BATCH_SIZE (they simply map to None)."
    )
    # The query was still issued only once.
    assert db.execute.call_count == 1, (
        "derive_coverage_summaries must still issue exactly 1 query when the "
        "batch exceeds _MAX_BATCH_SIZE."
    )


# ---------------------------------------------------------------------------
# CU-8: single-workspace wrapper delegates to batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_workspace_wrapper_uses_batch() -> None:
    """CU-8 — derive_coverage_summary delegates to derive_coverage_summaries.

    The single-workspace convenience function must share the batch code path
    so it never drifts into a separate implementation.
    """
    wid = uuid4()
    db = _make_db([(wid, 55)])

    with patch(
        "services.coverage_utils.derive_coverage_summaries",
        wraps=derive_coverage_summaries,
    ) as batch_spy:
        result = await derive_coverage_summary(wid, db)

    batch_spy.assert_called_once_with([wid], db)
    assert isinstance(result, CoverageSummary)
    assert result.percent == 55

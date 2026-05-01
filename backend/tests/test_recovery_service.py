from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from models import CreditLedger, Stage, Workspace
from services.pipeline.recovery_service import recover_stuck_stages


def _make_stuck_stage(minutes_old: int, workspace_id=None) -> Stage:
    return Stage(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        type="spec",
        status="in_progress",
        content=None,
        current_version=0,
        review_gate_acknowledged=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC) - timedelta(minutes=minutes_old),
    )


def _make_workspace(user_id=None, workspace_id=None) -> Workspace:
    w = Workspace(
        id=workspace_id or uuid4(),
        user_id=user_id or uuid4(),
        name="WS",
        problem_statement="build a todo app with authentication",
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    w.stages = []
    return w


def _make_ledger_entry(
    user_id, amount: int = -10, reason: str = "generate"
) -> CreditLedger:
    return CreditLedger(
        id=uuid4(),
        user_id=user_id,
        amount=amount,
        reason=reason,
        created_at=datetime.now(UTC),
    )


class _FakeResult:
    def __init__(self, value: Any = None, many: list | None = None) -> None:
        self._value = value
        self._many = many or []

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> "_FakeResult":
        return self

    def __iter__(self):
        yield from self._many


class _FakeDB:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = iter(responses)
        self.added: list[Any] = []
        self._committed = False

    async def execute(self, statement: Any) -> _FakeResult:
        try:
            val = next(self._responses)
        except StopIteration:
            val = None
        if isinstance(val, list):
            return _FakeResult(many=val)
        return _FakeResult(val)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self._committed = True

    async def refresh(self, instance: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_recover_stage_stuck_15_minutes() -> None:
    """Stage stuck 15 min is reset to draft and credits refunded."""
    user_id = uuid4()
    workspace_id = uuid4()
    stage = _make_stuck_stage(15, workspace_id=workspace_id)
    workspace = _make_workspace(user_id=user_id, workspace_id=workspace_id)
    ledger = _make_ledger_entry(user_id)

    db = _FakeDB(
        [
            [stage],  # stuck stages query
            workspace,  # workspace query
            ledger,  # ledger entry query
        ]
    )

    with patch(
        "services.pipeline.recovery_service.credit_service.refund",
        new=AsyncMock(),
    ) as mock_refund:
        count = await recover_stuck_stages(db)

    assert count == 1
    assert stage.status == "draft"
    assert db._committed is True
    mock_refund.assert_awaited_once_with(db, ledger.id)


@pytest.mark.asyncio
async def test_stages_stuck_9_minutes_not_recovered() -> None:
    """When DB returns no stuck stages (9-min stage filtered by SQL), count is 0."""
    # The actual time-based filter happens in SQL. This test simulates the DB
    # correctly returning no results for a stage that is only 9 minutes old.
    db = _FakeDB([[]])  # empty result — DB filtered out the recent stage

    count = await recover_stuck_stages(db)

    assert count == 0
    assert db._committed is False


@pytest.mark.asyncio
async def test_recover_no_ledger_entry_still_resets_stage() -> None:
    """Stage is reset to draft even if no matching ledger entry is found."""
    user_id = uuid4()
    workspace_id = uuid4()
    stage = _make_stuck_stage(15, workspace_id=workspace_id)
    workspace = _make_workspace(user_id=user_id, workspace_id=workspace_id)

    db = _FakeDB(
        [
            [stage],  # stuck stages
            workspace,  # workspace
            None,  # no ledger entry found
        ]
    )

    with patch(
        "services.pipeline.recovery_service.credit_service.refund",
        new=AsyncMock(),
    ) as mock_refund:
        count = await recover_stuck_stages(db)

    assert count == 1
    assert stage.status == "draft"
    mock_refund.assert_not_called()


@pytest.mark.asyncio
async def test_recover_missing_workspace_skips_stage() -> None:
    """Stage is skipped (not counted) if its workspace cannot be loaded."""
    workspace_id = uuid4()
    stage = _make_stuck_stage(15, workspace_id=workspace_id)

    db = _FakeDB(
        [
            [stage],  # stuck stages
            None,  # workspace not found
        ]
    )

    count = await recover_stuck_stages(db)

    assert count == 0
    assert stage.status == "in_progress"  # unchanged
    assert db._committed is False


@pytest.mark.asyncio
async def test_recover_multiple_stuck_stages() -> None:
    """Multiple stuck stages are all recovered in one pass."""
    user_id = uuid4()
    workspace_id = uuid4()
    stage1 = _make_stuck_stage(20, workspace_id=workspace_id)
    stage2 = _make_stuck_stage(30, workspace_id=workspace_id)
    workspace = _make_workspace(user_id=user_id, workspace_id=workspace_id)
    ledger1 = _make_ledger_entry(user_id)
    ledger2 = _make_ledger_entry(user_id, reason="regenerate")

    db = _FakeDB(
        [
            [stage1, stage2],  # stuck stages
            workspace,  # workspace for stage1
            ledger1,  # ledger for stage1
            workspace,  # workspace for stage2
            ledger2,  # ledger for stage2
        ]
    )

    with patch(
        "services.pipeline.recovery_service.credit_service.refund",
        new=AsyncMock(),
    ):
        count = await recover_stuck_stages(db)

    assert count == 2
    assert stage1.status == "draft"
    assert stage2.status == "draft"
    assert db._committed is True

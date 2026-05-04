from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from models import Stage
from services.pipeline.recovery_service import recover_stuck_stages


def _make_stuck_stage(
    minutes_old: int,
    workspace_id=None,
    deduction_ledger_id=None,
) -> Stage:
    return Stage(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        type="spec",
        status="in_progress",
        content=None,
        current_version=0,
        review_gate_acknowledged=False,
        deduction_ledger_id=deduction_ledger_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC) - timedelta(minutes=minutes_old),
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
async def test_recovery_uses_stored_deduction_id() -> None:
    """Stage recovery uses stage.deduction_ledger_id directly — no time-window query."""
    ledger_id = uuid4()
    stage = _make_stuck_stage(15, deduction_ledger_id=ledger_id)

    db = _FakeDB([[stage]])  # only the stuck-stages query

    with patch(
        "services.pipeline.recovery_service.credit_service.refund",
        new=AsyncMock(),
    ) as mock_refund:
        count = await recover_stuck_stages(db)

    assert count == 1
    assert stage.status == "draft"
    assert db._committed is True
    mock_refund.assert_awaited_once_with(db, ledger_id)


@pytest.mark.asyncio
async def test_recover_stage_stuck_15_minutes() -> None:
    """Stage stuck 15 min is reset to draft and credits refunded via stored ID."""
    ledger_id = uuid4()
    stage = _make_stuck_stage(15, deduction_ledger_id=ledger_id)

    db = _FakeDB([[stage]])

    with patch(
        "services.pipeline.recovery_service.credit_service.refund",
        new=AsyncMock(),
    ) as mock_refund:
        count = await recover_stuck_stages(db)

    assert count == 1
    assert stage.status == "draft"
    mock_refund.assert_awaited_once_with(db, ledger_id)


@pytest.mark.asyncio
async def test_stages_stuck_9_minutes_not_recovered() -> None:
    """When DB returns no stuck stages (9-min stage filtered by SQL), count is 0."""
    db = _FakeDB([[]])

    count = await recover_stuck_stages(db)

    assert count == 0
    assert db._committed is False


@pytest.mark.asyncio
async def test_recover_no_deduction_ledger_id_still_resets_stage() -> None:
    """Stage is reset to draft even if deduction_ledger_id is None (credits not refunded)."""
    stage = _make_stuck_stage(15, deduction_ledger_id=None)

    db = _FakeDB([[stage]])

    with patch(
        "services.pipeline.recovery_service.credit_service.refund",
        new=AsyncMock(),
    ) as mock_refund:
        count = await recover_stuck_stages(db)

    assert count == 1
    assert stage.status == "draft"
    mock_refund.assert_not_called()


@pytest.mark.asyncio
async def test_recover_multiple_stuck_stages() -> None:
    """Multiple stuck stages are all recovered in one pass using their stored IDs."""
    ledger_id1 = uuid4()
    ledger_id2 = uuid4()
    stage1 = _make_stuck_stage(20, deduction_ledger_id=ledger_id1)
    stage2 = _make_stuck_stage(30, deduction_ledger_id=ledger_id2)

    db = _FakeDB([[stage1, stage2]])

    with patch(
        "services.pipeline.recovery_service.credit_service.refund",
        new=AsyncMock(),
    ) as mock_refund:
        count = await recover_stuck_stages(db)

    assert count == 2
    assert stage1.status == "draft"
    assert stage2.status == "draft"
    assert db._committed is True
    assert mock_refund.await_count == 2
    calls = {c.args[1] for c in mock_refund.await_args_list}
    assert calls == {ledger_id1, ledger_id2}

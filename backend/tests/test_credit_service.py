from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from models import CreditLedger
from services.credit_service import CreditService, InsufficientCreditsError


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: Any, ex: int = 0) -> None:
        self._store[key] = str(value)

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)


class _FakeDB:
    def __init__(
        self,
        ledger: list[CreditLedger] | None = None,
        entity_lookup: CreditLedger | None = None,
        raise_integrity_error_on_flush: bool = False,
    ) -> None:
        self._ledger: list[CreditLedger] = ledger or []
        self._entity_lookup = entity_lookup
        self._raise_integrity_error = raise_integrity_error_on_flush
        self._execute_count = 0
        self.added: list[Any] = []
        self.rolled_back = False

    async def execute(self, statement: Any) -> Any:
        call = self._execute_count
        self._execute_count += 1
        # refund() first looks up the original deduction by ID
        if call == 0 and self._entity_lookup is not None:
            return _EntityResult(self._entity_lookup)
        return _LedgerQueryResult(list(self._ledger))

    def add(self, instance: Any) -> None:
        if isinstance(instance, CreditLedger):
            if not hasattr(instance, "id") or instance.id is None:
                instance.id = uuid4()
            self._ledger.append(instance)
        self.added.append(instance)

    async def flush(self) -> None:
        if self._raise_integrity_error:
            raise IntegrityError(None, None, Exception("duplicate"))

    async def rollback(self) -> None:
        self.rolled_back = True

    async def commit(self) -> None:
        pass


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _LedgerQueryResult:
    """Supports both scalar_one() (for get_balance) and scalars().all() (for deduct)."""

    def __init__(self, rows: list[CreditLedger]) -> None:
        self._rows = rows

    def scalar_one(self) -> int:
        return sum(r.amount for r in self._rows)

    def scalar_one_or_none(self) -> int:
        return self.scalar_one()

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _EntityResult:
    def __init__(self, entity: Any) -> None:
        self._entity = entity

    def scalar_one_or_none(self) -> Any:
        return self._entity

    def scalar_one(self) -> Any:
        return self._entity


@pytest.fixture
def svc() -> CreditService:
    return CreditService(redis_client=_FakeRedis())


@pytest.mark.asyncio
async def test_get_balance_returns_sum(svc: CreditService) -> None:
    user_id = uuid4()
    ledger = [
        CreditLedger(id=uuid4(), user_id=user_id, amount=50, reason="signup"),
        CreditLedger(id=uuid4(), user_id=user_id, amount=-10, reason="gen"),
    ]
    db = _FakeDB(ledger)
    assert await svc.get_balance(db, user_id) == 40


@pytest.mark.asyncio
async def test_get_balance_uses_cache_on_second_call(svc: CreditService) -> None:
    user_id = uuid4()
    redis = svc._redis
    assert isinstance(redis, _FakeRedis)
    redis._store[f"credits:{user_id}"] = "99"
    db = _FakeDB()
    assert await svc.get_balance(db, user_id) == 99
    assert not db.added


@pytest.mark.asyncio
async def test_deduct_raises_on_insufficient_balance(svc: CreditService) -> None:
    user_id = uuid4()
    db = _FakeDB()
    with pytest.raises(InsufficientCreditsError):
        await svc.deduct(db, user_id, 10, "gen")


@pytest.mark.asyncio
async def test_deduct_succeeds_when_balance_sufficient(svc: CreditService) -> None:
    user_id = uuid4()
    ledger = [CreditLedger(id=uuid4(), user_id=user_id, amount=50, reason="signup")]
    db = _FakeDB(ledger)
    entry = await svc.deduct(db, user_id, 10, "gen")
    assert entry.amount == -10
    assert any(e.amount == -10 for e in db._ledger)


@pytest.mark.asyncio
async def test_refund_inserts_positive_entry(svc: CreditService) -> None:
    user_id = uuid4()
    deduction = CreditLedger(id=uuid4(), user_id=user_id, amount=-10, reason="gen")
    db = _FakeDB(entity_lookup=deduction)

    await svc.refund(db, deduction.id)

    refund_entries = [e for e in db._ledger if e.amount > 0 and "refund" in e.reason]
    assert len(refund_entries) == 1
    assert refund_entries[0].amount == 10


@pytest.mark.asyncio
async def test_refund_is_idempotent(svc: CreditService) -> None:
    user_id = uuid4()
    deduction = CreditLedger(id=uuid4(), user_id=user_id, amount=-10, reason="gen")
    # Simulate DB enforcing the unique constraint by raising IntegrityError on flush
    db = _FakeDB(entity_lookup=deduction, raise_integrity_error_on_flush=True)

    # Must not raise — duplicate refund is silently swallowed
    await svc.refund(db, deduction.id)

    assert db.rolled_back


@pytest.mark.asyncio
async def test_refund_is_race_safe_via_integrity_error(svc: CreditService) -> None:
    user_id = uuid4()
    deduction = CreditLedger(id=uuid4(), user_id=user_id, amount=-10, reason="gen")
    db = _FakeDB(entity_lookup=deduction, raise_integrity_error_on_flush=True)

    # Concurrent call: db.flush() raises IntegrityError — must return silently
    await svc.refund(db, deduction.id)

    # db.rollback() must have been called to clear the failed transaction
    assert db.rolled_back


@pytest.mark.asyncio
async def test_credit_invalidates_cache(svc: CreditService) -> None:
    user_id = uuid4()
    redis = svc._redis
    assert isinstance(redis, _FakeRedis)
    redis._store[f"credits:{user_id}"] = "50"
    db = _FakeDB()
    await svc.credit(db, user_id, 20, "bonus")
    assert f"credits:{user_id}" not in redis._store

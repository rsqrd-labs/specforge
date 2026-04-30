from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

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
    ) -> None:
        self._ledger: list[CreditLedger] = ledger or []
        self._entity_lookup = entity_lookup
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> Any:
        if self._entity_lookup is not None:
            return _EntityResult(self._entity_lookup)
        total = sum(e.amount for e in self._ledger)
        return _SumResult(total)

    def add(self, instance: Any) -> None:
        if isinstance(instance, CreditLedger):
            if not hasattr(instance, "id") or instance.id is None:
                instance.id = uuid4()
            self._ledger.append(instance)
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


class _SumResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value

    def scalar_one_or_none(self) -> int:
        return self._value


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
async def test_credit_invalidates_cache(svc: CreditService) -> None:
    user_id = uuid4()
    redis = svc._redis
    assert isinstance(redis, _FakeRedis)
    redis._store[f"credits:{user_id}"] = "50"
    db = _FakeDB()
    await svc.credit(db, user_id, 20, "bonus")
    assert f"credits:{user_id}" not in redis._store

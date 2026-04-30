from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from middleware.credit_check import require_credits
from models import User


class _FakeDB:
    pass


class _FakeCreditService:
    def __init__(self, balance: int) -> None:
        self._balance = balance

    async def get_balance(self, db: _FakeDB, user_id) -> int:
        return self._balance


def _make_user() -> User:
    return User(
        id=uuid4(),
        email="test@example.com",
        google_id="g-123",
        name="Test",
        avatar_url=None,
    )


@pytest.mark.asyncio
async def test_require_credits_passes_when_balance_sufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import middleware.credit_check as mod

    monkeypatch.setattr(mod, "credit_service", _FakeCreditService(50))
    checker = require_credits(10)
    await checker(user=_make_user(), db=_FakeDB())


@pytest.mark.asyncio
async def test_require_credits_raises_402_when_balance_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import middleware.credit_check as mod

    monkeypatch.setattr(mod, "credit_service", _FakeCreditService(0))
    checker = require_credits(10)
    with pytest.raises(HTTPException) as exc_info:
        await checker(user=_make_user(), db=_FakeDB())
    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["code"] == "insufficient_credits"

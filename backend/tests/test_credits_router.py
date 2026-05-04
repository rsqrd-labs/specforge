from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import CreditLedger, User

_USER_ID = uuid4()
_USER = User(
    id=_USER_ID,
    email="test@example.com",
    google_id="google-123",
    name="Test User",
    avatar_url=None,
    created_at=datetime.now(UTC),
)


class _NoopPipeline:
    def zremrangebyscore(self, *args: Any) -> "_NoopPipeline":
        return self

    def zadd(self, *args: Any) -> "_NoopPipeline":
        return self

    def zcard(self, *args: Any) -> "_NoopPipeline":
        return self

    def expire(self, *args: Any) -> "_NoopPipeline":
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _NoopRedis:
    async def eval(self, *args, **kwargs) -> int:
        return 1

    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


_LEDGER_ENTRIES = [
    CreditLedger(
        id=uuid4(),
        user_id=_USER_ID,
        amount=-10,
        reason="generate",
        created_at=datetime.now(UTC),
    ),
    CreditLedger(
        id=uuid4(),
        user_id=_USER_ID,
        amount=50,
        reason="signup_bonus",
        created_at=datetime.now(UTC),
    ),
]


class _FakeDB:
    async def execute(self, statement: Any) -> Any:
        from unittest.mock import MagicMock

        result = MagicMock()
        result.scalars.return_value = iter(_LEDGER_ENTRIES)
        return result

    async def commit(self) -> None:
        pass

    async def refresh(self, instance: Any) -> None:
        pass


@pytest.fixture
def app():
    _app = create_app(redis_client=_NoopRedis())
    _app.dependency_overrides[get_current_user] = lambda: _USER
    return _app


@pytest.mark.asyncio
async def test_get_balance_returns_balance(app) -> None:
    async def _fake_db():
        yield _FakeDB()

    app.dependency_overrides[get_db] = _fake_db

    with patch(
        "services.credit_service.credit_service.get_balance",
        new_callable=AsyncMock,
        return_value=50,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/credits/balance")

    assert response.status_code == 200
    assert response.json()["balance"] == 50


@pytest.mark.asyncio
async def test_get_history_returns_entries(app) -> None:
    async def _fake_db():
        yield _FakeDB()

    app.dependency_overrides[get_db] = _fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/credits/history")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["reason"] == "generate"
    assert data[1]["reason"] == "signup_bonus"


@pytest.mark.asyncio
async def test_get_history_respects_limit(app) -> None:
    async def _fake_db():
        yield _FakeDB()

    app.dependency_overrides[get_db] = _fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/credits/history?limit=1")

    assert response.status_code == 200

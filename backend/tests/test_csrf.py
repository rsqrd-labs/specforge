from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import User
from services.security.csrf import generate_csrf_token, verify_csrf_token


def test_generate_and_verify_csrf_token_roundtrip() -> None:
    token = generate_csrf_token("session-123")
    assert verify_csrf_token(token, "session-123") is True


def test_verify_csrf_token_rejects_tampered_hmac() -> None:
    token = generate_csrf_token("session-123")
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert verify_csrf_token(tampered, "session-123") is False


def test_verify_csrf_token_rejects_expired_token() -> None:
    token = generate_csrf_token("session-123")
    assert verify_csrf_token(token, "session-123", max_age_seconds=-1) is False


class _NoopPipeline:
    def zremrangebyscore(self, *args: Any) -> "_NoopPipeline":
        return self

    def zadd(self, *args: Any) -> "_NoopPipeline":
        return self

    def zcard(self, *args: Any) -> "_NoopPipeline":
        return self

    def expire(self, *args: Any) -> "_NoopPipeline":
        return self

    async def execute(self) -> list[int]:
        return [0, 1, 1, 1]


class _NoopRedis:
    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


async def _fake_get_db():
    yield object()


@pytest.mark.asyncio
async def test_csrf_endpoint_returns_token_for_current_user() -> None:
    user = _make_user()
    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/auth/csrf-token",
            headers={"Authorization": "Bearer test-token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    csrf_token = response.json()["csrf_token"]
    assert verify_csrf_token(csrf_token, str(user.id)) is True


@pytest.mark.asyncio
async def test_mutating_request_with_valid_auth_without_csrf_returns_403() -> None:
    user = _make_user()
    token = jwt.encode({"sub": str(user.id)}, "test-secret")
    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/workspaces",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Test",
                "problem_statement": "A" * 60,
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mutating_request_with_valid_csrf_reaches_route() -> None:
    user = _make_user()
    token = jwt.encode({"sub": str(user.id)}, "test-secret")
    csrf_token = generate_csrf_token(str(user.id))
    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/workspaces",
            headers={
                "Authorization": f"Bearer {token}",
                "X-CSRF-Token": csrf_token,
            },
            json={
                "name": "Test",
                "problem_statement": "A" * 60,
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code != 403


def _make_user() -> User:
    return User(
        id=uuid4(),
        email="test@example.com",
        google_id="google-123",
        name="Test User",
        avatar_url=None,
        created_at=datetime.now(UTC),
    )

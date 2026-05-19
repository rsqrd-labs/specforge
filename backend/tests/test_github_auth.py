"""Tests for the GitHub OAuth routes and integrations router (T-149)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from config import settings
from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import User
from services.integrations import github_auth_service


_USER_ID = uuid4()
_USER = User(
    id=_USER_ID,
    email="user@example.com",
    google_id="google-id",
    name="Test User",
    avatar_url=None,
    credit_balance=0,
    created_at=datetime.now(UTC),
)


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self._store[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)

    async def aclose(self) -> None:  # called by lifespan teardown
        return None

    async def ping(self) -> bool:
        return True

    # required for rate-limit middleware fast-path
    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1


class _FakeSession:
    async def execute(self, statement: Any) -> Any:
        class _Result:
            def scalar_one_or_none(self) -> None:
                return None

        return _Result()

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None


async def _fake_get_db():
    yield _FakeSession()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(settings, "github_client_id", "test_client_id")
    monkeypatch.setattr(settings, "github_client_secret", "test_secret")

    application = create_app(redis_client=_FakeRedis())
    application.dependency_overrides[get_db] = _fake_get_db
    yield application
    application.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /auth/github
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_github_without_jwt_returns_401(app: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get("/auth/github")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_github_with_jwt_redirects_to_github(app: Any) -> None:
    app.dependency_overrides[get_current_user] = lambda: _USER

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get("/auth/github")

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert "github.com/login/oauth/authorize" in location
    assert "client_id=test_client_id" in location
    assert "scope=repo" in location  # urlencoded "repo,read:user"
    assert "state=" in location


@pytest.mark.asyncio
async def test_auth_github_returns_503_when_client_id_empty(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "github_client_id", "")
    app.dependency_overrides[get_current_user] = lambda: _USER

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get("/auth/github")

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# /auth/github/callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_github_callback_missing_state_returns_400(app: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get("/auth/github/callback?code=abc")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_auth_github_callback_tampered_state_returns_400(app: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get(
            "/auth/github/callback?code=abc&state=not-in-redis"
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_auth_github_callback_user_denied_redirects_with_error(
    app: Any,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get(
            "/auth/github/callback?error=access_denied"
        )

    assert response.status_code in (302, 303)
    assert "github_error=access_denied" in response.headers["location"]


# ---------------------------------------------------------------------------
# /integrations/github
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_integrations_github_unconnected_returns_disconnected_shape(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_integration(user_id: Any, db: Any) -> None:
        return None

    monkeypatch.setattr(github_auth_service, "get_integration", fake_get_integration)
    app.dependency_overrides[get_current_user] = lambda: _USER

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/integrations/github")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "github_username": None}


@pytest.mark.asyncio
async def test_get_integrations_github_connected_returns_username(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from models.user_integration import UserIntegration

    integration = UserIntegration(
        id=uuid4(),
        user_id=_USER_ID,
        provider="github",
        encrypted_token="encrypted",
        github_username="octocat",
        connected_at=datetime.now(UTC),
        last_used_at=None,
    )

    async def fake_get_integration(user_id: Any, db: Any) -> UserIntegration:
        return integration

    monkeypatch.setattr(github_auth_service, "get_integration", fake_get_integration)
    app.dependency_overrides[get_current_user] = lambda: _USER

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/integrations/github")

    assert response.status_code == 200
    assert response.json() == {"connected": True, "github_username": "octocat"}


@pytest.mark.asyncio
async def test_delete_integrations_github_returns_204_when_absent(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_disconnect(user_id: Any, db: Any) -> None:
        return None

    monkeypatch.setattr(github_auth_service, "disconnect_github", fake_disconnect)
    app.dependency_overrides[get_current_user] = lambda: _USER

    # CSRF middleware is bypassed for tokens-derived headers; supply the same
    # CSRF header pattern used by the FE Axios client. Tests for other
    # mutating routes use the same shortcut.
    from services.security.csrf import generate_csrf_token

    csrf = generate_csrf_token(str(_USER_ID))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            "/integrations/github",
            headers={
                "Authorization": "Bearer valid_token",
                "X-CSRF-Token": csrf,
            },
        )

    assert response.status_code == 204

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
from services.auth_service import AuthError
from services.auth_service import auth_service as _auth_service
from services.credit_service import credit_service as _credit_service

_USER_ID = uuid4()
_USER = User(
    id=_USER_ID,
    email="test@example.com",
    google_id="google-123",
    name="Test User",
    avatar_url=None,
    created_at=datetime.now(UTC),
)


class _FakeSession:
    async def execute(self, statement: Any) -> None:
        return None


async def _fake_get_db():
    yield _FakeSession()


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


@pytest.fixture
def app():
    application = create_app(redis_client=_NoopRedis())
    application.dependency_overrides[get_db] = _fake_get_db
    yield application
    application.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_auth_google_redirects_to_google(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_url() -> tuple[str, str]:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
            "browser-binding-secret",
        )

    monkeypatch.setattr(_auth_service, "get_google_auth_url", fake_get_url)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get("/auth/google")

    assert response.status_code in (302, 307)
    assert "accounts.google.com" in response.headers["location"]
    # F5: the redirect plants the login-CSRF binding cookie (HttpOnly, dev name)
    # so the callback can bind the state to this browser.
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "sf_oauth_state=browser-binding-secret" in set_cookie_header
    assert "HttpOnly" in set_cookie_header


@pytest.mark.asyncio
async def test_get_auth_google_uses_host_prefixed_cookie_in_production(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: in production the binding cookie carries the __Host- prefix with Secure
    and NO Domain attribute — the property that makes cookie-tossing impossible."""

    async def fake_get_url() -> tuple[str, str]:
        return ("https://accounts.google.com/o/oauth2/v2/auth?x=1", "binding-secret")

    monkeypatch.setattr(_auth_service, "get_google_auth_url", fake_get_url)
    monkeypatch.setattr(settings, "environment", "production")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="https://api.test", follow_redirects=False
    ) as client:
        response = await client.get("/auth/google")

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "__Host-sf_oauth_state=binding-secret" in set_cookie_header
    assert "Secure" in set_cookie_header
    assert "samesite=none" in set_cookie_header.lower()
    assert "Path=/" in set_cookie_header
    # __Host- is void if a Domain attribute is present — assert there is none.
    assert "Domain=" not in set_cookie_header
    assert "domain=" not in set_cookie_header


@pytest.mark.asyncio
async def test_get_auth_me_with_valid_token_returns_user(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_balance(db: Any, user_id: Any) -> int:
        return 50

    monkeypatch.setattr(_credit_service, "get_balance", fake_get_balance)
    app.dependency_overrides[get_current_user] = lambda: _USER

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer valid_token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["credit_balance"] == 50
    assert data["id"] == str(_USER_ID)


@pytest.mark.asyncio
async def test_get_auth_me_with_no_token_returns_401(app: Any) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_auth_logout_clears_cookie(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_revoke(token: str) -> None:
        pass

    monkeypatch.setattr(_auth_service, "revoke", fake_revoke)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            cookies={"refresh_token": "some_refresh_token"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "refresh_token" in set_cookie_header
    assert "Path=/auth" in set_cookie_header


@pytest.mark.asyncio
async def test_refresh_cookie_uses_local_dev_security_attributes(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_handle_callback(
        code: str, state: str, state_binding: str | None, db: Any
    ) -> tuple[str, str]:
        return "access-token", "refresh-token"

    monkeypatch.setattr(_auth_service, "handle_callback", fake_handle_callback)
    monkeypatch.setattr(settings, "environment", "development")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/callback?code=test-code&state=test-state")

    assert response.status_code == 200
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "refresh_token=refresh-token" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "Secure" not in set_cookie_header
    assert "samesite=lax" in set_cookie_header.lower()
    assert "Path=/auth" in set_cookie_header
    assert "Max-Age=604800" in set_cookie_header


@pytest.mark.asyncio
async def test_refresh_cookie_uses_cross_site_production_attributes(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_handle_callback(
        code: str, state: str, state_binding: str | None, db: Any
    ) -> tuple[str, str]:
        return "access-token", "refresh-token"

    monkeypatch.setattr(_auth_service, "handle_callback", fake_handle_callback)
    monkeypatch.setattr(settings, "environment", "production")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.get("/auth/callback?code=test-code&state=test-state")

    assert response.status_code == 200
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "refresh_token=refresh-token" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "Secure" in set_cookie_header
    assert "samesite=none" in set_cookie_header.lower()
    assert "Path=/auth" in set_cookie_header
    assert "Max-Age=604800" in set_cookie_header


@pytest.mark.asyncio
async def test_callback_rejects_state_binding_failure(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: when the state/binding check fails, the callback 401s, issues no refresh
    cookie, and clears the single-use binding cookie."""

    async def fake_handle_callback(
        code: str, state: str, state_binding: str | None, db: Any
    ) -> tuple[str, str]:
        raise AuthError("Invalid or expired OAuth state")

    monkeypatch.setattr(_auth_service, "handle_callback", fake_handle_callback)
    monkeypatch.setattr(settings, "environment", "development")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/callback?code=test-code&state=test-state")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired OAuth state"}
    set_cookie_header = response.headers.get("set-cookie", "")
    # No session is issued on the failure path...
    assert "refresh_token=" not in set_cookie_header
    # ...and the binding cookie is cleared (deletion sets an empty value).
    assert "sf_oauth_state=" in set_cookie_header

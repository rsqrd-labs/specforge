"""Unit and integration tests for CSRF token generation and verification.

Covers:
  CU-1  Round-trip: generate then verify → True
  CU-2  Tampered HMAC → False
  CU-3  Expired timestamp → False (no Redis call)
  CU-4  Same token used twice → second call raises HTTPException(403)
  CU-5  Redis unavailable (ConnectionError) → fail open (True, WARNING logged)
  CU-6  Redis not set (None) → fail open (True, WARNING logged)

  CM-1  Mutating request without CSRF header → 403
  CM-2  Mutating request with valid CSRF header → request reaches route
  CM-3  POST /auth/logout without CSRF → 403
  CM-4  POST /auth/logout with valid CSRF → reaches route (not 403)
  CM-5  GET /auth/csrf-token → returns usable CSRF token

HF-6 — T-203.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import middleware.csrf as csrf_module
from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import User
from services.security.csrf import generate_csrf_token, verify_csrf_token

# ---------------------------------------------------------------------------
# Redis stubs
# ---------------------------------------------------------------------------


class _TrackingRedis:
    """In-memory SETNX-tracking stub for CSRF nonce replay tests."""

    def __init__(self) -> None:
        self._nonces: set[str] = set()

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx:
            if key in self._nonces:
                return None  # SETNX → key already exists → replay
            self._nonces.add(key)
            return True
        self._nonces.add(key)
        return True


class _SpyRedis:
    """Records whether set() was called; always succeeds."""

    def __init__(self) -> None:
        self.set_called = False

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        self.set_called = True
        return True


class _FailingRedis:
    """Simulates a Redis connection failure on every set() call."""

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("Redis unavailable")


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
    """Noop Redis for full-stack tests that don't need replay tracking."""

    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        # SETNX always succeeds — no replay tracking in noop stub.
        return True

    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


async def _fake_get_db():
    yield object()


# ---------------------------------------------------------------------------
# CU-1: Round-trip — generate then verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_and_verify_csrf_token_roundtrip() -> None:
    """CU-1 — generate_csrf_token + verify_csrf_token must be a valid round-trip."""
    redis = _TrackingRedis()
    token = generate_csrf_token("session-123")
    assert await verify_csrf_token(token, "session-123", redis) is True


# ---------------------------------------------------------------------------
# CU-2: Tampered HMAC → False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_csrf_token_rejects_tampered_hmac() -> None:
    """CU-2 — A token with a corrupted HMAC must be rejected before Redis."""
    spy = _SpyRedis()
    token = generate_csrf_token("session-123")
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    result = await verify_csrf_token(tampered, "session-123", spy)
    assert result is False
    assert not spy.set_called, (
        "Redis must NOT be contacted when the HMAC is invalid — "
        "the token is structurally invalid before replay tracking is relevant."
    )


# ---------------------------------------------------------------------------
# CU-3: Expired timestamp → False and NO Redis call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_csrf_token_rejects_expired_token() -> None:
    """CU-3 — An expired token must be rejected before the Redis round-trip.

    No unnecessary Redis call should occur when the timestamp has already
    exceeded max_age_seconds — verifying expiry is cheaper than a network
    call and must always gate the SETNX step.  HF-6 — T-203.
    """
    spy = _SpyRedis()
    token = generate_csrf_token("session-123")
    result = await verify_csrf_token(token, "session-123", spy, max_age_seconds=-1)
    assert result is False, (
        "verify_csrf_token must return False for an expired token "
        "(max_age_seconds=-1 forces immediate expiry). HF-6 — T-203."
    )
    assert not spy.set_called, (
        "Redis set() must NOT be called for expired tokens — "
        "no unnecessary round-trip should occur. HF-6 — T-203."
    )


# ---------------------------------------------------------------------------
# CU-4: Double-use → second call raises 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_csrf_token_rejects_replay() -> None:
    """CU-4 — The second use of the same token must raise HTTPException(403).

    After the first call successfully claims the nonce via SETNX, the
    second call finds the nonce already present in Redis and raises 403.
    This closes the 1-hour replay window: a CSRF token stolen from the
    browser cannot be reused by an attacker.  HF-6 — T-203.
    """
    redis = _TrackingRedis()
    token = generate_csrf_token("session-replay-test")

    # First use must succeed.
    result = await verify_csrf_token(token, "session-replay-test", redis)
    assert result is True

    # Second use of the same token must raise 403.
    with pytest.raises(HTTPException) as exc_info:
        await verify_csrf_token(token, "session-replay-test", redis)

    assert exc_info.value.status_code == 403, (
        "Replayed CSRF token must raise HTTPException(403). "
        f"Got status_code={exc_info.value.status_code}. HF-6 — T-203."
    )
    assert "already used" in exc_info.value.detail, (
        "Replay error detail must mention 'already used'. "
        f"Got: {exc_info.value.detail!r}. HF-6 — T-203."
    )


# ---------------------------------------------------------------------------
# CU-5: Redis ConnectionError → fail open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_csrf_token_redis_unavailable_fails_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CU-5 — ConnectionError from Redis must fail open with a WARNING log.

    A transient Redis outage must not block mutating requests entirely.
    Replay protection is degraded, but availability is preserved.
    HF-6 — T-203.
    """
    redis = _FailingRedis()
    token = generate_csrf_token("session-redis-fail")

    with caplog.at_level(logging.WARNING, logger="services.security.csrf"):
        result = await verify_csrf_token(token, "session-redis-fail", redis)

    assert result is True, (
        "verify_csrf_token must fail open (return True) when Redis raises "
        "ConnectionError. HF-6 — T-203."
    )
    assert any(
        "redis_error" in record.message or "fail-open" in record.message
        for record in caplog.records
    ), (
        "verify_csrf_token must log a WARNING when Redis is unavailable "
        "so the degradation is visible in logs/alerts. HF-6 — T-203."
    )


# ---------------------------------------------------------------------------
# CU-6: redis=None → fail open (pre-lifespan window)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_csrf_token_redis_none_fails_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CU-6 — redis=None must fail open with a WARNING log.

    When app.state.redis has not yet been populated (pre-lifespan window)
    the middleware passes None.  Replay protection is unavailable but the
    request must not be blocked.  HF-6 — T-203.
    """
    token = generate_csrf_token("session-none-redis")

    with caplog.at_level(logging.WARNING, logger="services.security.csrf"):
        result = await verify_csrf_token(token, "session-none-redis", None)

    assert result is True, (
        "verify_csrf_token must fail open (return True) when redis=None. "
        "HF-6 — T-203."
    )
    assert any(
        "not_available" in record.message or "fail-open" in record.message
        for record in caplog.records
    ), "verify_csrf_token must log a WARNING when redis=None. HF-6 — T-203."


# ---------------------------------------------------------------------------
# CM-5: Full-stack — GET /auth/csrf-token returns a usable token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csrf_endpoint_returns_token_for_current_user() -> None:
    """CM-5 — GET /auth/csrf-token must return a token that verifies correctly."""
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
    # Verify the token is structurally valid (does not check replay; _NoopRedis
    # never rejects SETNX so a fresh token always passes).
    assert await verify_csrf_token(csrf_token, str(user.id), _TrackingRedis()) is True


# ---------------------------------------------------------------------------
# CM-1: Mutating request without CSRF header → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mutating_request_with_valid_auth_without_csrf_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CM-1 — POST without X-CSRF-Token must return 403."""
    user = _make_user()
    monkeypatch.setattr(
        csrf_module,
        "decode_access_token_claims",
        lambda t: (
            {"sub": str(user.id), "type": "access"} if t == "valid-token" else None
        ),
    )
    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/workspaces",
            headers={"Authorization": "Bearer valid-token"},
            json={
                "name": "Test",
                "problem_statement": (
                    "I want to build a task management web app for teams to create "
                    "projects, assign tasks, track status, and notify users."
                ),
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# CM-2: Mutating request with valid CSRF header → reaches route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mutating_request_with_valid_csrf_reaches_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CM-2 — POST with a valid X-CSRF-Token must not be blocked by CSRF middleware."""
    user = _make_user()
    csrf_token = generate_csrf_token(str(user.id))
    monkeypatch.setattr(
        csrf_module,
        "decode_access_token_claims",
        lambda t: (
            {"sub": str(user.id), "type": "access"} if t == "valid-token" else None
        ),
    )
    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/workspaces",
            headers={
                "Authorization": "Bearer valid-token",
                "X-CSRF-Token": csrf_token,
            },
            json={
                "name": "Test",
                "problem_statement": (
                    "I want to build a task management web app for teams to create "
                    "projects, assign tasks, track status, and notify users."
                ),
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code != 403


# ---------------------------------------------------------------------------
# CM-3: POST /auth/logout without CSRF → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_with_bearer_token_but_no_csrf_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CM-3 — POST /auth/logout must be CSRF-protected when an access token is present.

    HF-6 — T-203.
    """
    user = _make_user()
    monkeypatch.setattr(
        csrf_module,
        "decode_access_token_claims",
        lambda t: (
            {"sub": str(user.id), "type": "access"} if t == "valid-token" else None
        ),
    )
    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={"Authorization": "Bearer valid-token"},
            cookies={"refresh_token": "some_token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# CM-4: POST /auth/logout with valid CSRF → succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_with_bearer_token_and_valid_csrf_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CM-4 — POST /auth/logout passes CSRF check when a valid token is supplied."""
    from services.auth_service import auth_service as _auth_service_instance

    user = _make_user()
    csrf_token = generate_csrf_token(str(user.id))
    monkeypatch.setattr(
        csrf_module,
        "decode_access_token_claims",
        lambda t: (
            {"sub": str(user.id), "type": "access"} if t == "valid-token" else None
        ),
    )
    monkeypatch.setattr(_auth_service_instance, "revoke", lambda t: None)

    app = create_app(redis_client=_NoopRedis())
    # /auth is a CSRF fail-closed prefix (F2): a healthy Redis must be present or
    # the middleware 403s. ASGITransport does not run lifespan, so populate
    # app.state.redis explicitly to model a live-Redis production request.
    app.state.redis = _NoopRedis()
    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={
                "Authorization": "Bearer valid-token",
                "X-CSRF-Token": csrf_token,
            },
            cookies={"refresh_token": "some_token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code != 403


# ---------------------------------------------------------------------------
# F2 (issue #42): fail-closed override on sensitive prefixes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_csrf_fail_closed_redis_none_raises_403() -> None:
    """F2 — fail_closed=True + redis=None must raise 403, not fail open.

    On a Redis outage a replayed billing/auth mutation must be refused rather
    than silently allowed. issue #42.
    """
    token = generate_csrf_token("session-fc-none")
    with pytest.raises(HTTPException) as exc_info:
        await verify_csrf_token(token, "session-fc-none", None, fail_closed=True)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_csrf_fail_closed_redis_error_raises_403() -> None:
    """F2 — fail_closed=True + Redis ConnectionError must raise 403. issue #42."""
    token = generate_csrf_token("session-fc-err")
    with pytest.raises(HTTPException) as exc_info:
        await verify_csrf_token(
            token, "session-fc-err", _FailingRedis(), fail_closed=True
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_csrf_fail_closed_healthy_redis_still_passes() -> None:
    """F2 — fail_closed must NOT change the happy path (healthy Redis). issue #42."""
    redis = _TrackingRedis()
    token = generate_csrf_token("session-fc-ok")
    assert (
        await verify_csrf_token(token, "session-fc-ok", redis, fail_closed=True) is True
    )


@pytest.mark.asyncio
async def test_verify_csrf_default_still_fails_open_on_ungated_path() -> None:
    """F2 — the default (fail_closed=False) keeps failing open. issue #42."""
    token = generate_csrf_token("session-open")
    assert await verify_csrf_token(token, "session-open", None) is True
    assert await verify_csrf_token(token, "session-open", _FailingRedis()) is True


@pytest.mark.asyncio
async def test_billing_prefix_is_fail_closed_by_default_config() -> None:
    """F2 — /billing and /auth are in the default fail-closed prefix set. issue #42."""
    from config import settings

    prefixes = settings.csrf_fail_closed_prefix_tuple
    assert "/billing".startswith(prefixes)
    assert "/auth".startswith(prefixes)
    # A non-sensitive path must NOT match the fail-closed set.
    assert not "/workspaces".startswith(prefixes)


# ---------------------------------------------------------------------------
# F7 (issue #42): CSRF is skipped for requests with no Bearer token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mutating_request_without_bearer_skips_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7 — a mutating request carrying no Bearer token is not blocked by CSRF.

    INVARIANT (pinned): this app authenticates state-changing calls with a
    header token, not a cookie session, so there is no cross-site request to
    forge when no Bearer is present. If a cookie-authenticated mutating endpoint
    is ever added, this skip becomes a CSRF hole — this test then documents the
    behavior that must be revisited. issue #42.
    """
    user = _make_user()
    # No Authorization header ⇒ _session_id_from_authorization returns None.
    monkeypatch.setattr(csrf_module, "decode_access_token_claims", lambda t: None)
    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _fake_get_db
    # Override auth so the route is reachable and we isolate the CSRF decision:
    # if CSRF blocked it we'd see 403; anything else means CSRF let it through.
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/workspaces",
            json={
                "name": "Test",
                "problem_statement": (
                    "I want to build a task management web app for teams to "
                    "create projects, assign tasks, track status, notify users."
                ),
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code != 403, (
        "CSRF middleware must skip requests with no Bearer token — the app is "
        "header-token authenticated, so there is no forgeable session. issue #42."
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_user() -> User:
    return User(
        id=uuid4(),
        email="test@example.com",
        google_id="google-123",
        name="Test User",
        avatar_url=None,
        created_at=datetime.now(UTC),
    )

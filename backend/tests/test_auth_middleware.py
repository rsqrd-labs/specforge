from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from middleware import auth
from models import User
from services.auth_service import AuthError


class FakeResult:
    def __init__(self, value: User | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> User | None:
        return self.value


class FakeDB:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.execute_count = 0

    async def execute(self, statement: Any) -> FakeResult:
        self.execute_count += 1
        return FakeResult(self.user)


class FakeRequest:
    def __init__(self, claims: dict | None = None) -> None:
        self.state = SimpleNamespace()
        if claims is not None:
            self.state.jwt_claims = claims


class FakeAuthService:
    def __init__(
        self, claims: dict[str, str] | None = None, error: Exception | None = None
    ):
        self.claims = claims
        self.error = error
        self.call_count = 0

    def verify_access_token(self, token: str) -> dict[str, str]:
        self.call_count += 1
        if self.error is not None:
            raise self.error
        if self.claims is None:
            raise AuthError("invalid")
        return self.claims


@pytest.mark.asyncio
async def test_get_current_user_with_valid_token_returns_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.clear_user_cache()
    user = User(
        id=uuid4(),
        email="dev@example.com",
        google_id="google-user-id",
        name="Dev User",
        avatar_url=None,
    )
    monkeypatch.setattr(
        auth,
        "auth_service",
        FakeAuthService({"sub": str(user.id)}),
    )

    current_user = await auth.get_current_user(FakeRequest(), "token", FakeDB(user))  # type: ignore[arg-type]

    assert current_user is user


@pytest.mark.asyncio
async def test_get_current_user_with_expired_token_raises_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.clear_user_cache()
    monkeypatch.setattr(
        auth,
        "auth_service",
        FakeAuthService(error=AuthError("expired")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(FakeRequest(), "expired", FakeDB(None))  # type: ignore[arg-type]

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_with_missing_token_raises_401() -> None:
    auth.clear_user_cache()
    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(FakeRequest(), None, FakeDB(None))  # type: ignore[arg-type]

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_optional_user_returns_none_for_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.clear_user_cache()
    monkeypatch.setattr(
        auth,
        "auth_service",
        FakeAuthService(error=AuthError("expired")),
    )

    optional_user = await auth.get_optional_user(FakeRequest(), "expired", FakeDB(None))  # type: ignore[arg-type]

    assert optional_user is None


@pytest.mark.asyncio
async def test_get_current_user_uses_cached_claims_skips_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.clear_user_cache()
    """When request.state.jwt_claims is set, verify_access_token is not called."""
    user = User(
        id=uuid4(),
        email="cached@example.com",
        google_id="g-id",
        name="Cached User",
        avatar_url=None,
    )
    fake_service = FakeAuthService({"sub": str(user.id)})
    monkeypatch.setattr(auth, "auth_service", fake_service)

    request = FakeRequest(claims={"sub": str(user.id)})
    current_user = await auth.get_current_user(request, None, FakeDB(user))  # type: ignore[arg-type]

    assert current_user is user
    assert fake_service.call_count == 0


@pytest.mark.asyncio
async def test_get_current_user_without_cache_falls_back_to_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.clear_user_cache()
    """Without cached claims, verify_access_token is called exactly once."""
    user = User(
        id=uuid4(),
        email="fallback@example.com",
        google_id="g-id",
        name="Fallback User",
        avatar_url=None,
    )
    fake_service = FakeAuthService({"sub": str(user.id)})
    monkeypatch.setattr(auth, "auth_service", fake_service)

    request = FakeRequest()  # no cached claims
    current_user = await auth.get_current_user(request, "token", FakeDB(user))  # type: ignore[arg-type]

    assert current_user is user
    assert fake_service.call_count == 1


@pytest.mark.asyncio
async def test_get_current_user_reuses_short_lived_user_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.clear_user_cache()
    user = User(
        id=uuid4(),
        email="cache-hit@example.com",
        google_id="g-id",
        name="Cache Hit",
        avatar_url=None,
    )
    fake_service = FakeAuthService({"sub": str(user.id)})
    monkeypatch.setattr(auth, "auth_service", fake_service)
    db = FakeDB(user)

    first = await auth.get_current_user(FakeRequest(), "token", db)  # type: ignore[arg-type]
    second = await auth.get_current_user(FakeRequest(), "token", db)  # type: ignore[arg-type]

    assert first is user
    assert second.id == user.id
    assert second.email == user.email
    assert db.execute_count == 1
    auth.clear_user_cache()

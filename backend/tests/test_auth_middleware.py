from __future__ import annotations

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

    async def execute(self, statement: Any) -> FakeResult:
        return FakeResult(self.user)


class FakeAuthService:
    def __init__(
        self, claims: dict[str, str] | None = None, error: Exception | None = None
    ):
        self.claims = claims
        self.error = error

    def verify_access_token(self, token: str) -> dict[str, str]:
        if self.error is not None:
            raise self.error
        if self.claims is None:
            raise AuthError("invalid")
        return self.claims


@pytest.mark.asyncio
async def test_get_current_user_with_valid_token_returns_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    current_user = await auth.get_current_user("token", None, FakeDB(user))  # type: ignore[arg-type]

    assert current_user is user


@pytest.mark.asyncio
async def test_get_current_user_with_expired_token_raises_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth,
        "auth_service",
        FakeAuthService(error=AuthError("expired")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user("expired", None, FakeDB(None))  # type: ignore[arg-type]

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_with_missing_token_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(None, None, FakeDB(None))  # type: ignore[arg-type]

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_optional_user_returns_none_for_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth,
        "auth_service",
        FakeAuthService(error=AuthError("expired")),
    )

    optional_user = await auth.get_optional_user("expired", None, FakeDB(None))  # type: ignore[arg-type]

    assert optional_user is None

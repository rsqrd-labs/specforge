from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from models import User
from services.auth_service import AuthError, AuthService


class FakeResult:
    def __init__(self, value: User | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> User | None:
        return self.value


class FakeDB:
    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.added: list[Any] = []
        self.committed = False
        self.refreshed: list[Any] = []

    async def execute(self, statement: Any) -> FakeResult:
        return FakeResult(self.user)

    def add(self, instance: Any) -> None:
        if isinstance(instance, User):
            instance.id = uuid4()
            self.user = instance
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, instance: Any) -> None:
        self.refreshed.append(instance)


class FakeCreditService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int, str]] = []

    async def credit(
        self,
        db: FakeDB,
        user_id: UUID,
        amount: int,
        reason: str,
    ) -> None:
        self.calls.append((user_id, amount, reason))


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, name: str, value: str, ex: int) -> None:
        self.values[name] = value

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def delete(self, *names: str) -> None:
        for name in names:
            self.values.pop(name, None)


class FakeResponse:
    def json(self) -> dict[str, str]:
        return {
            "sub": "google-user-id",
            "email": "dev@example.com",
            "name": "Dev User",
            "picture": "https://example.com/avatar.png",
        }


class FakeOAuthClient:
    def create_authorization_url(self, *args: Any, **kwargs: Any) -> tuple[str, str]:
        return ("https://accounts.google.com/o/oauth2/v2/auth?client_id=test", "state")

    async def fetch_token(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        return {"access_token": "google-token"}

    async def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse()


@pytest.fixture()
def signing_keys() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def make_service(
    signing_keys: tuple[str, str], redis: FakeRedis | None = None
) -> AuthService:
    private_key, public_key = signing_keys
    return AuthService(
        redis_client=redis or FakeRedis(),
        oauth_client=FakeOAuthClient(),
        signup_credit_service=FakeCreditService(),
        jwt_private_key=private_key,
        jwt_public_key=public_key,
    )


@pytest.mark.asyncio
async def test_handle_callback_creates_new_user(signing_keys: tuple[str, str]) -> None:
    service = make_service(signing_keys)
    db = FakeDB()

    access_token, refresh_token = await service.handle_callback("code", db)  # type: ignore[arg-type]

    assert access_token
    assert refresh_token
    assert db.user is not None
    assert db.user.email == "dev@example.com"
    assert db.user.google_id == "google-user-id"
    assert db.committed is True
    assert service.credit_service.calls == [(db.user.id, 50, "signup_bonus")]


@pytest.mark.asyncio
async def test_refresh_tokens_rotates_jti(signing_keys: tuple[str, str]) -> None:
    redis = FakeRedis()
    service = make_service(signing_keys, redis)
    user = User(
        id=uuid4(),
        email="dev@example.com",
        google_id="google-user-id",
        name="Dev User",
        avatar_url=None,
    )
    refresh_token = service._create_token(user.id, "refresh", 60)
    old_jti = service._decode_refresh_token(refresh_token)["jti"]
    await redis.set(service._session_key(old_jti), str(user.id), ex=60)

    access_token, new_refresh_token = await service.refresh_tokens(
        refresh_token,
        FakeDB(user),  # type: ignore[arg-type]
    )

    assert access_token
    assert new_refresh_token != refresh_token
    assert await redis.get(service._session_key(old_jti)) is None
    new_jti = service._decode_refresh_token(new_refresh_token)["jti"]
    assert await redis.get(service._session_key(new_jti)) == str(user.id)


@pytest.mark.asyncio
async def test_refresh_tokens_with_revoked_token_raises(
    signing_keys: tuple[str, str],
) -> None:
    service = make_service(signing_keys)
    user = User(
        id=uuid4(),
        email="dev@example.com",
        google_id="google-user-id",
        name="Dev User",
        avatar_url=None,
    )
    refresh_token = service._create_token(user.id, "refresh", 60)

    with pytest.raises(AuthError):
        await service.refresh_tokens(refresh_token, FakeDB(user))  # type: ignore[arg-type]


def test_verify_access_token_with_expired_token_raises(
    signing_keys: tuple[str, str],
) -> None:
    private_key, _public_key = signing_keys
    service = make_service(signing_keys)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "type": "access",
            "iat": datetime.now(UTC) - timedelta(minutes=30),
            "exp": datetime.now(UTC) - timedelta(minutes=15),
        },
        private_key,
        algorithm="RS256",
    )

    with pytest.raises(AuthError):
        service.verify_access_token(token)

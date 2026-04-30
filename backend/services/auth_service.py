from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from authlib.integrations.httpx_client import AsyncOAuth2Client
from jose import ExpiredSignatureError, JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import User
from services.credit_service import CreditService, credit_service

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # nosec B105
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = ("openid", "email", "profile")
ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 7
SESSION_PREFIX = "session:"


class AuthError(Exception):
    pass


class RedisSessionStore(Protocol):
    async def set(self, name: str, value: str, ex: int) -> Any: ...

    async def get(self, name: str) -> Any: ...

    async def delete(self, *names: str) -> Any: ...


class AuthService:
    def __init__(
        self,
        redis_client: RedisSessionStore | None = None,
        oauth_client: AsyncOAuth2Client | None = None,
        signup_credit_service: CreditService | None = None,
        jwt_private_key: str | None = None,
        jwt_public_key: str | None = None,
    ) -> None:
        self.redis = redis_client or Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        self.oauth_client = oauth_client or AsyncOAuth2Client(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scope=" ".join(GOOGLE_SCOPES),
            redirect_uri=self._redirect_uri,
        )
        self.credit_service = signup_credit_service or credit_service
        self.jwt_private_key = jwt_private_key or settings.jwt_private_key
        self.jwt_public_key = jwt_public_key or settings.jwt_public_key

    @property
    def _redirect_uri(self) -> str:
        return f"{settings.frontend_url.rstrip('/')}/auth/callback"

    def get_google_auth_url(self) -> str:
        authorization_url, _state = self.oauth_client.create_authorization_url(
            GOOGLE_AUTHORIZE_URL,
            scope=" ".join(GOOGLE_SCOPES),
            redirect_uri=self._redirect_uri,
        )
        return authorization_url

    async def handle_callback(self, code: str, db: AsyncSession) -> tuple[str, str]:
        await self._maybe_await(
            self.oauth_client.fetch_token(
                GOOGLE_TOKEN_URL,
                code=code,
                grant_type="authorization_code",
                redirect_uri=self._redirect_uri,
            )
        )
        response = await self.oauth_client.get(GOOGLE_USERINFO_URL)
        user_info = response.json()

        user = await self._upsert_google_user(user_info, db)
        access_token = self._create_token(user.id, "access", ACCESS_TOKEN_MINUTES)
        refresh_token = self._create_token(
            user.id,
            "refresh",
            REFRESH_TOKEN_DAYS * 24 * 60,
        )
        refresh_claims = self._decode_refresh_token(refresh_token)
        await self._store_refresh_session(
            refresh_claims["jti"],
            str(user.id),
        )

        return access_token, refresh_token

    async def refresh_tokens(
        self,
        refresh_token: str,
        db: AsyncSession,
    ) -> tuple[str, str]:
        claims = self._decode_refresh_token(refresh_token)
        old_jti = claims["jti"]
        user_id = claims["sub"]
        session_key = self._session_key(old_jti)

        if await self.redis.get(session_key) is None:
            raise AuthError("Refresh token has been revoked")

        await self.redis.delete(session_key)
        user = await self._get_user_by_id(UUID(user_id), db)
        if user is None:
            raise AuthError("User not found")

        access_token = self._create_token(user.id, "access", ACCESS_TOKEN_MINUTES)
        new_refresh_token = self._create_token(
            user.id,
            "refresh",
            REFRESH_TOKEN_DAYS * 24 * 60,
        )
        new_refresh_claims = self._decode_refresh_token(new_refresh_token)
        await self._store_refresh_session(
            new_refresh_claims["jti"],
            str(user.id),
        )

        return access_token, new_refresh_token

    async def revoke(self, refresh_token: str) -> None:
        claims = self._decode_refresh_token(refresh_token)
        await self.redis.delete(self._session_key(claims["jti"]))

    def verify_access_token(self, token: str) -> dict[str, Any]:
        claims = self._decode_token(token)
        if claims.get("type") != "access":
            raise AuthError("Invalid access token")
        return claims

    async def _upsert_google_user(
        self,
        user_info: dict[str, Any],
        db: AsyncSession,
    ) -> User:
        google_id = self._required_claim(user_info, "sub")
        email = self._required_claim(user_info, "email")

        result = await db.execute(select(User).where(User.google_id == google_id))
        user = result.scalar_one_or_none()
        is_new_user = user is None

        if user is None:
            user = User(
                email=email,
                google_id=google_id,
                name=user_info.get("name"),
                avatar_url=user_info.get("picture"),
            )
            db.add(user)
        else:
            user.email = email
            user.name = user_info.get("name")
            user.avatar_url = user_info.get("picture")

        await db.flush()

        if is_new_user:
            await self.credit_service.credit(db, user.id, 50, "signup_bonus")

        await db.commit()
        await db.refresh(user)
        return user

    async def _get_user_by_id(self, user_id: UUID, db: AsyncSession) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    def _create_token(
        self,
        user_id: UUID,
        token_type: str,
        expires_in_minutes: int,
    ) -> str:
        now = datetime.now(UTC)
        claims = {
            "sub": str(user_id),
            "jti": str(uuid4()),
            "type": token_type,
            "iat": now,
            "exp": now + timedelta(minutes=expires_in_minutes),
        }
        return jwt.encode(claims, self.jwt_private_key, algorithm="RS256")

    def _decode_refresh_token(self, token: str) -> dict[str, Any]:
        claims = self._decode_token(token)
        if claims.get("type") != "refresh":
            raise AuthError("Invalid refresh token")
        return claims

    def _decode_token(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, self.jwt_public_key, algorithms=["RS256"])
        except ExpiredSignatureError as exc:
            raise AuthError("Token has expired") from exc
        except JWTError as exc:
            raise AuthError("Invalid token") from exc

    async def _store_refresh_session(self, jti: str, user_id: str) -> None:
        await self.redis.set(
            self._session_key(jti),
            user_id,
            ex=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        )

    def _session_key(self, jti: str) -> str:
        return f"{SESSION_PREFIX}{jti}"

    def _required_claim(self, user_info: dict[str, Any], key: str) -> str:
        value = user_info.get(key)
        if not isinstance(value, str) or not value:
            raise AuthError(f"Google user info missing {key}")
        return value

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value


auth_service = AuthService()

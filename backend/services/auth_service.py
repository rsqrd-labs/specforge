from __future__ import annotations

import inspect
import json
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
REFRESH_REPLAY_GRACE_SECONDS = 30
SESSION_PREFIX = "session:"
CONSUMED_SESSION_PREFIX = "session_consumed:"
USER_SESSIONS_PREFIX = "user_sessions:"
OAUTH_STATE_PREFIX = "oauth:state:"
OAUTH_STATE_TTL = 600  # 10 minutes


class AuthError(Exception):
    pass


class RedisSessionStore(Protocol):
    async def set(self, name: str, value: str, ex: int) -> Any: ...

    async def get(self, name: str) -> Any: ...

    async def delete(self, *names: str) -> Any: ...

    async def sadd(self, name: str, *values: str) -> Any: ...

    async def srem(self, name: str, *values: str) -> Any: ...

    async def smembers(self, name: str) -> Any: ...

    async def expire(self, name: str, time: int) -> Any: ...


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

    async def get_google_auth_url(self) -> str:
        authorization_url, state = self.oauth_client.create_authorization_url(
            GOOGLE_AUTHORIZE_URL,
            scope=" ".join(GOOGLE_SCOPES),
            redirect_uri=self._redirect_uri,
        )
        await self.redis.set(f"{OAUTH_STATE_PREFIX}{state}", "1", ex=OAUTH_STATE_TTL)
        return authorization_url

    async def handle_callback(
        self, code: str, state: str, db: AsyncSession
    ) -> tuple[str, str]:
        state_key = f"{OAUTH_STATE_PREFIX}{state}"
        if not await self.redis.get(state_key):
            raise AuthError("Invalid or expired OAuth state")
        await self.redis.delete(state_key)

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
            replayed = await self._maybe_replay_recent_refresh(old_jti, user_id, db)
            if replayed is not None:
                return replayed
            await self._revoke_all_user_sessions(user_id)
            raise AuthError("Refresh token has been revoked")

        await self.redis.delete(session_key)
        await self.redis.srem(self._user_sessions_key(user_id), old_jti)
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
        await self._store_consumed_refresh(
            old_jti,
            str(user.id),
            new_refresh_token,
        )

        return access_token, new_refresh_token

    async def revoke(self, refresh_token: str) -> None:
        claims = self._decode_refresh_token(refresh_token)
        user_id = claims["sub"]
        jti = claims["jti"]
        await self.redis.delete(self._session_key(claims["jti"]))
        await self.redis.srem(self._user_sessions_key(user_id), jti)

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
        user_sessions_key = self._user_sessions_key(user_id)
        await self.redis.sadd(user_sessions_key, jti)
        await self.redis.expire(user_sessions_key, REFRESH_TOKEN_DAYS * 24 * 60 * 60)

    def _session_key(self, jti: str) -> str:
        return f"{SESSION_PREFIX}{jti}"

    def _consumed_session_key(self, jti: str) -> str:
        return f"{CONSUMED_SESSION_PREFIX}{jti}"

    def _user_sessions_key(self, user_id: str) -> str:
        return f"{USER_SESSIONS_PREFIX}{user_id}"

    async def _store_consumed_refresh(
        self,
        old_jti: str,
        user_id: str,
        new_refresh_token: str,
    ) -> None:
        await self.redis.set(
            self._consumed_session_key(old_jti),
            json.dumps(
                {
                    "user_id": user_id,
                    "refresh_token": new_refresh_token,
                }
            ),
            ex=REFRESH_REPLAY_GRACE_SECONDS,
        )

    async def _maybe_replay_recent_refresh(
        self,
        old_jti: str,
        user_id: str,
        db: AsyncSession,
    ) -> tuple[str, str] | None:
        raw = await self.redis.get(self._consumed_session_key(old_jti))
        if raw is None:
            return None

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if payload.get("user_id") != user_id:
            return None

        refresh_token = payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            return None

        claims = self._decode_refresh_token(refresh_token)
        if claims.get("sub") != user_id:
            return None
        if await self.redis.get(self._session_key(claims["jti"])) is None:
            return None

        user = await self._get_user_by_id(UUID(user_id), db)
        if user is None:
            raise AuthError("User not found")
        access_token = self._create_token(user.id, "access", ACCESS_TOKEN_MINUTES)
        return access_token, refresh_token

    async def _revoke_all_user_sessions(self, user_id: str) -> None:
        user_sessions_key = self._user_sessions_key(user_id)
        session_ids = await self.redis.smembers(user_sessions_key)
        session_keys = [self._session_key(str(jti)) for jti in session_ids]
        if session_keys:
            await self.redis.delete(*session_keys)
        await self.redis.delete(user_sessions_key)

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


def decode_access_token_claims(token: str) -> dict[str, Any] | None:
    """Verify token signature and return claims, or None if invalid/expired."""
    try:
        claims = jwt.decode(token, settings.jwt_public_key, algorithms=["RS256"])
        if claims.get("type") != "access":
            return None
        return claims
    except JWTError:
        return None

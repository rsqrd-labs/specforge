import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from database import get_db, get_shared_redis
from models import User
from services.auth_service import AuthError, auth_service

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/google", auto_error=False)

# Short-lived authenticated-user cache, backed by Redis (LF-1).
#
# This is a Redis-backed L2 cache (not a per-process dict) so that an
# invalidation — issued after any credit_balance mutation — propagates to EVERY
# API worker, not just the one that handled the mutating request. With the prior
# in-process OrderedDict, a multi-worker / horizontally-scaled deployment served
# stale credit_balance values for up to the TTL on workers that never saw the
# invalidation. The authoritative credit deduction is always a fresh
# SELECT FOR UPDATE in credit_service (so this never affected charging
# correctness); the cache exists to avoid a User row read per request and to
# keep the *displayed* balance coherent across workers.
#
# Resilience: every Redis interaction is best-effort. A cache read/write/delete
# failure (Redis down or a transport error) is logged and swallowed, falling
# through to the authoritative database read — a degraded cache must never break
# authentication. An in-request memo (request.state) collapses repeated
# get_current_user dependencies in a single request to one resolution.
_USER_CACHE_TTL_SECONDS = 30
_USER_CACHE_PREFIX = "authuser:"
_REQUEST_USER_ATTR = "_auth_cached_user"


def _cache_key(user_id: UUID) -> str:
    return f"{_USER_CACHE_PREFIX}{user_id}"


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    cached_claims = getattr(request.state, "jwt_claims", None)
    if cached_claims is not None:
        claims = cached_claims
    else:
        if not token:
            raise _unauthorized()
        try:
            claims = auth_service.verify_access_token(token)
        except (AuthError, KeyError, TypeError, ValueError) as exc:
            raise _unauthorized() from exc

    try:
        user_id = UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise _unauthorized() from exc

    # In-request memo: several dependencies may depend on get_current_user in one
    # request; resolve the user (and any Redis/DB hit) exactly once. Keyed on the
    # token subject so a memo can never return a different user.
    memo = getattr(request.state, _REQUEST_USER_ATTR, None)
    if memo is not None and memo.id == user_id:
        return memo

    user = await _load_user(db, user_id)
    if user is None:
        raise _unauthorized()
    setattr(request.state, _REQUEST_USER_ATTR, user)
    return user


async def get_optional_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    has_cached_claims = getattr(request.state, "jwt_claims", None) is not None
    if not token and not has_cached_claims:
        return None
    try:
        return await get_current_user(request=request, token=token, db=db)
    except HTTPException:
        return None


async def _load_user(db: AsyncSession, user_id: UUID) -> User | None:
    cached = await _cached_user(user_id)
    if cached is not None:
        return cached

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        await _cache_user(user)
    return user


def _serialize_user(user: User) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": str(user.id),
        "email": user.email,
        "google_id": user.google_id,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "credit_balance": int(user.credit_balance or 0),
    }
    created_at = getattr(user, "created_at", None)
    if isinstance(created_at, datetime):
        payload["created_at"] = created_at.isoformat()
    return payload


def _deserialize_user(payload: dict[str, object]) -> User:
    fields: dict[str, object] = {
        "id": UUID(str(payload["id"])),
        "email": payload["email"],
        "google_id": payload["google_id"],
        "name": payload["name"],
        "avatar_url": payload["avatar_url"],
        "credit_balance": int(payload["credit_balance"]),  # type: ignore[arg-type]
    }
    created_at = payload.get("created_at")
    if isinstance(created_at, str):
        fields["created_at"] = datetime.fromisoformat(created_at)
    return User(**fields)


async def _cached_user(user_id: UUID) -> User | None:
    """Return the Redis-cached user, or None on miss / unusable entry / Redis error.

    Never raises into the auth path: a Redis failure logs a non-sensitive warning
    and is treated as a miss so the caller reads the authoritative DB row.
    """
    try:
        raw = await get_shared_redis().get(_cache_key(user_id))
    except Exception:
        logger.warning("auth.user_cache_read_failed", exc_info=True)
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        return _deserialize_user(payload)
    except (ValueError, TypeError, KeyError):
        # Corrupt / schema-changed entry — treat as a miss and re-read.
        logger.warning("auth.user_cache_entry_unusable")
        return None


async def _cache_user(user: User) -> None:
    """Cache the user's display fields with the short TTL (best-effort)."""
    if user.id is None:
        return
    try:
        await get_shared_redis().set(
            _cache_key(user.id),
            json.dumps(_serialize_user(user)),
            ex=_USER_CACHE_TTL_SECONDS,
        )
    except Exception:
        logger.warning("auth.user_cache_write_failed", exc_info=True)


async def clear_user_cache(user_id: UUID | None = None) -> None:
    """Drop a single user's cache entry, or all entries when ``user_id`` is None.

    Best-effort: a Redis error is logged and swallowed (a stale entry self-expires
    within the TTL). Clearing all entries scans only the ``authuser:`` keyspace.
    """
    redis = get_shared_redis()
    try:
        if user_id is None:
            keys = [
                key async for key in redis.scan_iter(match=f"{_USER_CACHE_PREFIX}*")
            ]
            if keys:
                await redis.delete(*keys)
        else:
            await redis.delete(_cache_key(user_id))
    except Exception:
        logger.warning("auth.user_cache_clear_failed", exc_info=True)


async def invalidate_user_cache(user_id: UUID) -> None:
    """Remove ``user_id`` from the shared cache so the next request re-reads the DB.

    Call this after any operation that modifies the user's credit_balance. Because
    the cache is Redis-backed, the invalidation is visible to every worker, not
    only the one that handled the mutating request (LF-1). Best-effort: a Redis
    error is logged and swallowed — the stale entry self-expires within the TTL.
    """
    try:
        await get_shared_redis().delete(_cache_key(user_id))
    except Exception:
        logger.warning("auth.user_cache_invalidate_failed", exc_info=True)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

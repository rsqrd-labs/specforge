import time
from collections import OrderedDict
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from database import get_db
from models import User
from services.auth_service import AuthError, auth_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/google", auto_error=False)
_USER_CACHE_TTL_SECONDS = 30
_USER_CACHE_MAX_SIZE = 4096

# NOTE: _USER_CACHE is per-process. In multi-worker deployments (uvicorn
# --workers > 1 or Railway horizontal scaling), invalidate_user_cache() only
# clears the cache in the worker that receives the invalidation call. Other
# workers may continue serving stale credit_balance values for up to
# _USER_CACHE_TTL_SECONDS (default: 30 s).
#
# For single-worker deployments this is not a problem. For multi-worker
# deployments, the 30-second TTL bounds the maximum staleness window.
#
# TODO(LF-1): migrate to Redis-backed user cache for multi-worker deployments.
# See docs/RUNBOOK.md §4 for detection and workaround procedures.
_USER_CACHE: OrderedDict[UUID, tuple[float, dict[str, Any]]] = OrderedDict()


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

    user = await _load_user(db, user_id)
    if user is None:
        raise _unauthorized()
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
    cached = _cached_user(user_id)
    if cached is not None:
        return cached

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        _cache_user(user)
    return user


def _cached_user(user_id: UUID) -> User | None:
    cached = _USER_CACHE.get(user_id)
    if cached is None:
        return None

    expires_at, payload = cached
    if expires_at <= time.monotonic():
        _USER_CACHE.pop(user_id, None)
        return None

    _USER_CACHE.move_to_end(user_id)
    return User(**payload)


def _cache_user(user: User) -> None:
    user_id = user.id
    if user_id is None:
        return

    payload = {
        "id": user.id,
        "email": user.email,
        "google_id": user.google_id,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "credit_balance": int(user.credit_balance or 0),
    }
    created_at = getattr(user, "created_at", None)
    if isinstance(created_at, datetime):
        payload["created_at"] = created_at

    _USER_CACHE[user_id] = (time.monotonic() + _USER_CACHE_TTL_SECONDS, payload)
    _USER_CACHE.move_to_end(user_id)
    while len(_USER_CACHE) > _USER_CACHE_MAX_SIZE:
        _USER_CACHE.popitem(last=False)


def clear_user_cache(user_id: UUID | None = None) -> None:
    if user_id is None:
        _USER_CACHE.clear()
        return
    _USER_CACHE.pop(user_id, None)


def invalidate_user_cache(user_id: UUID) -> None:
    """Remove ``user_id`` from the auth middleware cache.

    Call this after any operation that modifies the user's credit_balance so
    the next request re-reads the authoritative value from the database rather
    than serving a stale cache entry.  H-4 — T-180.
    """
    _USER_CACHE.pop(user_id, None)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

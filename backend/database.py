from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Redis helpers — H-1 (T-177)
#
# All routers and services must obtain Redis via get_redis() or
# get_shared_redis() rather than calling Redis.from_url() themselves.  This
# ensures every caller shares the single connection pool created at lifespan
# and avoids un-pooled per-request connections.
# ---------------------------------------------------------------------------

_shared_redis: "Redis | None" = None


def _initialize_redis(client: "Redis") -> None:
    """Called from app lifespan to register the shared pool.

    Must be called before the first request that touches Redis.
    """
    global _shared_redis
    _shared_redis = client


def get_redis(request: Request) -> "Redis":
    """FastAPI dependency: return the app's shared Redis pool.

    Use this with ``Depends(get_redis)`` in router functions so they share
    the connection pool established at lifespan rather than opening a new
    connection per request.  Falls back to the module-level singleton for
    test clients that do not run the lifespan.
    """
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        return redis
    return get_shared_redis()


def get_shared_redis() -> "Redis":
    """Return the shared Redis client for use outside of a request context.

    Services and background tasks that cannot receive a ``Request`` object
    call this function.  In production the pool is always initialized by the
    time any service method is invoked.  In tests, callers that need Redis
    should inject a fake client via the service's constructor parameter.
    """
    if _shared_redis is not None:
        return _shared_redis
    # Fallback: create a fresh client.  This path is only reachable when the
    # lifespan has not yet run (e.g. a service singleton is accessed before
    # app startup in an integration test without explicit injection).
    from redis.asyncio import Redis

    return Redis.from_url(settings.redis_url, decode_responses=True)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

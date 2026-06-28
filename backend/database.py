from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _unique_prepared_statement_name() -> str:
    """Generate a process-unique prepared-statement name (F3 — pooler mode).

    Behind a transaction-mode pooler (PgBouncer) consecutive statements can land
    on different backend connections, so asyncpg's default numeric statement
    names collide ("prepared statement ... already exists"). A UUID name per
    prepare avoids the collision (SQLAlchemy asyncpg+PgBouncer guidance).
    """
    return f"__asyncpg_{uuid4()}__"


def _engine_connect_args() -> dict:
    """asyncpg connect args for the postgres engine (F9 + F3 — scalability audit).

    F9: ``statement_timeout`` and ``idle_in_transaction_session_timeout`` are set
    as asyncpg ``server_settings`` so every pooled connection enforces them at the
    database, bounding a runaway query and freeing a connection left idle in an
    open transaction (defence-in-depth).

    F3: when ``db_transaction_pooler_mode`` is on, additionally disable
    SQLAlchemy's prepared-statement cache and assign each prepared statement a
    unique name so the engine is safe behind a transaction-mode pooler
    (PgBouncer). The server_settings guards remain applied — the pooler must
    allow them via ``ignore_startup_parameters`` (shipped deploy/pgbouncer.ini).

    All of this is postgres-only: a non-postgres DATABASE_URL (e.g. a sqlite test
    URL) gets no asyncpg-specific args, so the engine still builds. Migrations run
    on a separate engine and are unaffected.
    """
    if not settings.database_url.startswith(("postgresql", "postgres")):
        return {}
    connect_args: dict = {}
    server_settings: dict[str, str] = {}
    if settings.db_statement_timeout_ms > 0:
        server_settings["statement_timeout"] = str(settings.db_statement_timeout_ms)
    if settings.db_idle_in_transaction_timeout_ms > 0:
        server_settings["idle_in_transaction_session_timeout"] = str(
            settings.db_idle_in_transaction_timeout_ms
        )
    if server_settings:
        connect_args["server_settings"] = server_settings
    if settings.db_transaction_pooler_mode:
        # Disable the prepared-statement cache and use unique names so the engine
        # tolerates a transaction-mode pooler routing statements across backends.
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = _unique_prepared_statement_name
        # asyncpg ALSO caches its own type-introspection queries as server-side
        # prepared statements, independently of SQLAlchemy's cache above. Those
        # collide under a transaction pooler too, so disable asyncpg's cache as
        # well (forwarded straight to asyncpg.connect). This is the asyncpg
        # statement_cache_size=0 its own pgbouncer error message recommends.
        connect_args["statement_cache_size"] = 0
    return connect_args


async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    # F9: a saturated pool fast-fails (a retryable 503) instead of blocking the
    # SQLAlchemy default 30s per checkout under load.
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=3600,
    connect_args=_engine_connect_args(),
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


def build_redis_client() -> "Redis":
    """Construct a Redis client with a bounded, health-checked pool (F8).

    The single source of truth for how every Redis client in the process is
    built — the lifespan pool, the health-check probe, and the
    ``get_shared_redis()`` fallback all go through here so none can drift back to
    an unbounded ``Redis.from_url(...)``. Bounds the connection pool, sets a
    fast-fail socket timeout, enables TCP keepalive, and runs idle-connection
    health checks so a connection left stale after a Redis failover is detected
    and recycled rather than handed out and surfaced as an error.
    """
    from redis.asyncio import Redis

    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_socket_connect_timeout,
        socket_keepalive=True,
        health_check_interval=settings.redis_health_check_interval,
    )


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
    # app startup in an integration test without explicit injection).  Built
    # through the same bounded/health-checked factory as the lifespan pool (F8).
    return build_redis_client()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

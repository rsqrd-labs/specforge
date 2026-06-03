"""Durable background job queue (Phase 21 — T-269).

SpecForge's first durable background processing. The only prior mechanism
(``asyncio.create_task``) dies on deploy and times out long exports, so all
GitHub I/O moves onto an ``arq`` worker (planning decision, Plan §24.1). This
module owns the *request-path* side of the queue:

  - the ``arq`` Redis pool wiring (reuses ``REDIS_URL``),
  - a typed :func:`enqueue` helper that **fails closed** when the queue is
    unavailable (never a silent inline fallback), and
  - the shared job base contract used by every worker job: idempotency keying,
    exponential backoff + jitter retries up to ``JOB_MAX_TRIES``, and a
    dead-letter record (+ metric + alert log) on exhaustion with a documented
    manual-replay path.

Outbound jobs are keyed by ``push_id`` / ``increment_id`` (passed as the arq
``_job_id``) so a duplicate enqueue dedups and a crash resumes the *same* job
rather than starting a second one. The worker itself lives in ``worker.py``.
"""

from __future__ import annotations

import functools
import json
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.worker import Retry

from config import settings
from services.integrations.github_governor import GitHubThrottledError
from services.observability import (
    GITHUB_JOB_DEADLETTERED_TOTAL,
    GITHUB_JOB_RETRIES_TOTAL,
    GITHUB_THROTTLED_TOTAL,
)

logger = structlog.get_logger(__name__)

# Job base contract (Plan §24.1 / T-269).
JOB_MAX_TRIES = 5
# Exponential backoff base/cap (seconds) with full jitter so retries from many
# jobs do not thunder against a recovering GitHub.
_RETRY_BACKOFF_BASE_SECONDS = 5.0
_RETRY_BACKOFF_CAP_SECONDS = 600.0

# Redis key holding dead-letter records (a capped list) for manual replay.
DEAD_LETTER_KEY = "gh:deadletter"
_DEAD_LETTER_MAX = 1000

_pool: ArqRedis | None = None


class QueueUnavailableError(Exception):
    """The durable queue could not be reached.

    Raised by :func:`enqueue` so request handlers fail closed with a clear
    "background processing unavailable" error rather than silently running work
    inline on the request path.
    """


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def get_arq_pool() -> ArqRedis:
    """Return the process-wide arq Redis pool, creating it on first use."""
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def close_arq_pool() -> None:
    """Close the pool (worker/app shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue(
    job: str,
    *args: Any,
    job_id: str | None = None,
    defer_by: float | None = None,
    pool: ArqRedis | None = None,
    **kwargs: Any,
) -> str | None:
    """Enqueue a worker job, failing closed if the queue is unreachable.

    ``job_id`` is the idempotency key (the outbound ``push_id`` /
    ``increment_id``): arq drops a duplicate enqueue for a job id already
    queued/in-flight, returning ``None``, so re-submitting an export does not
    start a second push.

    Raises :class:`QueueUnavailableError` if the Redis-backed queue cannot be
    reached — the caller surfaces a 503, never an inline fallback.
    """
    try:
        arq_pool = pool or await get_arq_pool()
        job_def = await arq_pool.enqueue_job(
            job, *args, _job_id=job_id, _defer_by=defer_by, **kwargs
        )
    except QueueUnavailableError:
        raise
    except Exception as exc:  # Redis/connection failure → fail closed.
        logger.error("github.queue.enqueue_failed", job=job)
        raise QueueUnavailableError("background processing is unavailable") from exc
    return job_def.job_id if job_def is not None else None


def _retry_backoff_seconds(attempt: int) -> float:
    """Exponential backoff with full jitter, capped (attempt is 1-based)."""
    ceiling = min(
        _RETRY_BACKOFF_CAP_SECONDS,
        _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
    )
    return random.uniform(0, ceiling)  # nosec B311 — jitter, not security


def _safe_arg(value: Any) -> Any:
    """Return a log/record-safe representation of a job arg.

    Never persists raw webhook payloads or other ``bytes`` (which may carry
    secrets); keeps only identifying scalars so a dead-lettered job can be
    replayed by id.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


async def record_dead_letter(
    pool: ArqRedis,
    *,
    job: str,
    job_id: str | None,
    args: tuple[Any, ...],
    error: str,
) -> None:
    """Append a dead-letter record to Redis for manual replay (RUNBOOK).

    Stores only the job name, id, sanitized args, and the error class name —
    never tokens, the App private key, or raw payloads (Plan §24.10).
    """
    record = json.dumps(
        {
            "job": job,
            "job_id": job_id,
            "args": [_safe_arg(a) for a in args],
            "error": error,
            "ts": datetime.now(UTC).isoformat(),
        }
    )
    try:
        await pool.lpush(DEAD_LETTER_KEY, record)
        await pool.ltrim(DEAD_LETTER_KEY, 0, _DEAD_LETTER_MAX - 1)
    except Exception:  # pragma: no cover — best-effort; never mask the failure
        logger.error("github.queue.dead_letter_persist_failed", job=job)


async def _requeue_throttled(
    ctx: dict[str, Any],
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    throttle: GitHubThrottledError,
) -> None:
    """Re-enqueue a throttled job deferred, off the dead-letter try budget.

    The re-enqueue uses a **fresh** arq job id (``_job_id`` omitted), not the
    current ``ctx['job_id']``. Re-enqueuing under the in-flight id is a no-op in
    arq: while the job is running ``arq:job:{job_id}`` still exists so
    ``enqueue_job`` dedups and drops it, and on the clean return arq's
    ``finish_job`` deletes that key by id — either way the requeue is lost. A
    fresh id survives both. Idempotency does **not** depend on the arq id: the
    job body is checkpoint-idempotent on its *argument* key (``push_id`` /
    ``increment_id``) and the per-repo lock (T-274) serializes, so a re-run with
    a new arq id resumes the same work and never duplicates a side effect.

    Because the current attempt returns cleanly (not ``Retry``), ``job_try`` does
    not advance, so sustained rate-limiting — a large export issuing far more
    writes than the ~80/min secondary budget — backs off indefinitely instead of
    dead-lettering a healthy export at ``JOB_MAX_TRIES``.
    """
    GITHUB_THROTTLED_TOTAL.labels(job=name, reason=throttle.reason).inc()
    logger.info(
        "github.job.throttled",
        job=name,
        job_id=ctx.get("job_id"),
        reason=throttle.reason,
        retry_after=round(throttle.retry_after, 1),
    )
    try:
        await ctx["redis"].enqueue_job(
            name,
            *args,
            _defer_by=throttle.retry_after,
            **kwargs,
        )
    except Exception:  # pragma: no cover — a periodic reconcile/backfill recovers
        # If the re-enqueue itself fails (Redis blip), the job is dropped this
        # cycle; the T-273 reconcile_drift cron re-derives and re-enqueues the
        # outstanding work from the push ledger, so no state is lost.
        logger.error("github.job.throttle_requeue_failed", job=name)


F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def github_job(name: str) -> Callable[[F], F]:
    """Decorator giving a worker job the shared base contract.

    On a transient failure the job retries with exponential backoff + jitter
    (incrementing ``specforge_github_job_retries_total``) up to
    :data:`JOB_MAX_TRIES`; after the cap it is dead-lettered (record + alert log
    + ``specforge_github_job_deadlettered_total``) and the exception is
    swallowed so arq does not retry forever. Idempotency/resume is the job
    body's responsibility (it is keyed by ``push_id``/``increment_id`` and must
    not duplicate side effects on re-run).
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            job_try = int(ctx.get("job_try", 1) or 1)
            try:
                return await fn(ctx, *args, **kwargs)
            except Retry:
                raise
            except GitHubThrottledError as throttle:
                # Backpressure, not failure (T-274): the per-installation governor
                # hit a GitHub rate limit (403/429) or its token bucket / per-repo
                # lock is saturated. Requeue the job deferred WITHOUT consuming the
                # dead-letter try budget — re-enqueue self rather than raising
                # ``Retry`` (which would increment job_try and eventually
                # dead-letter a perfectly healthy job under sustained throttling).
                await _requeue_throttled(ctx, name, args, kwargs, throttle)
                return None
            except Exception as exc:
                error = type(exc).__name__
                if job_try >= JOB_MAX_TRIES:
                    GITHUB_JOB_DEADLETTERED_TOTAL.labels(job=name).inc()
                    logger.error(
                        "github.job.deadlettered",
                        job=name,
                        job_id=ctx.get("job_id"),
                        attempts=job_try,
                        error=error,
                    )
                    await record_dead_letter(
                        ctx["redis"],
                        job=name,
                        job_id=ctx.get("job_id"),
                        args=args,
                        error=error,
                    )
                    # Swallow so arq marks the job finished (dead-lettered),
                    # not re-queued indefinitely. Manual replay re-enqueues by id.
                    return None
                GITHUB_JOB_RETRIES_TOTAL.labels(job=name).inc()
                logger.warning(
                    "github.job.retry", job=name, attempt=job_try, error=error
                )
                raise Retry(defer=_retry_backoff_seconds(job_try)) from exc

        return wrapper  # type: ignore[return-value]

    return decorator

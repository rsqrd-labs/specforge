"""Durable background job queue (Phase 21 — T-269).

Thought2Build's first durable background processing. The only prior mechanism
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
from prometheus_client import Counter

from config import settings
from services.integrations.github_governor import GitHubThrottledError
from services.observability import (
    BILLING_JOB_DEADLETTERED_TOTAL,
    BILLING_JOB_RETRIES_TOTAL,
    GITHUB_JOB_DEADLETTERED_TOTAL,
    GITHUB_JOB_RETRIES_TOTAL,
    GITHUB_THROTTLED_TOTAL,
    LLM_BATCH_JOB_DEADLETTERED_TOTAL,
    LLM_BATCH_JOB_RETRIES_TOTAL,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Live-queue split (F5 — scalability audit).
#
# A single worker queue means a burst of bulk GitHub exports (up to 1800s each)
# fills the worker's job slots and starves the latency-sensitive jobs behind
# them — most damagingly the billing webhook processor, which grants credits a
# user has already PAID for. We split the live queues by latency class:
#
#   - BULK_QUEUE_NAME = arq's DEFAULT queue. Kept as the default deliberately so
#     any job enqueued by older code (or in flight across the deploy) still
#     drains — nothing is stranded at the cutover. Carries the GitHub bulk I/O
#     (export/periodic-backfill/increment/projects) and the LLM eval batch jobs.
#   - FAST_QUEUE_NAME = a separate queue drained by its OWN worker process
#     (`arq worker.FastWorkerSettings`), so a bulk-export storm cannot occupy its
#     job slots. Carries paid credit grants and latency-sensitive GitHub updates.
#   - GENERATION_QUEUE_NAME = a separate durable lane for paid LLM artifacts,
#     isolated from both bulk exports and webhook/credit latency.
#
# Routing is by job NAME via queue_for_job(), so every enqueue() call site is
# unchanged — the home queue is resolved centrally (DRY) and worker.py partitions
# the three WorkerSettings classes off the SAME table.
#
# DEPLOY INVARIANT: the FastWorkerSettings process MUST be running in every
# environment, or fast-queue jobs (paid grants) never drain. The
# thought2build_worker_queue_oldest_age_seconds{queue="arq:queue:fast"} and
# thought2build_billing_webhook_pending_age_seconds alerts are the backstop signal
# for a missing/stalled fast worker (RUNBOOK §9.6 / §16).
# ---------------------------------------------------------------------------
BULK_QUEUE_NAME = "arq:queue"  # arq's built-in default queue name.
FAST_QUEUE_NAME = "arq:queue:fast"
# Paid LLM generation has a different failure and capacity profile from both
# GitHub bulk I/O and billing webhooks.  It therefore gets an independently
# scalable worker lane: a deploy/restart may interrupt a worker process, but arq
# retains and retries the generation job under its durable generation-run id.
GENERATION_QUEUE_NAME = "arq:queue:generation"

# Jobs whose latency is user-/money-visible and must not queue behind a bulk
# GitHub-export storm (audit §F5): paid credit grants, webhook reconciliation,
# the PR status check, and an explicit user-requested inbound refresh. Periodic
# repository backfill remains on bulk so fleet-wide recovery cannot starve this
# lane.
_FAST_QUEUE_JOBS = frozenset(
    {
        "billing_process_webhook",
        "pr_check",
        "reconcile_issue_event",
        "refresh_task_states",
    }
)

_GENERATION_QUEUE_JOBS = frozenset({"stage_generate"})


def queue_for_job(job: str) -> str:
    """Resolve a job's home queue from its name (F5 — single source of truth).

    Used by both enqueue() (to route a producer's job) and worker.py (to
    partition which functions each WorkerSettings class drains), so the split can
    never drift between the producer and consumer sides.
    """
    if job in _GENERATION_QUEUE_JOBS:
        return GENERATION_QUEUE_NAME
    return FAST_QUEUE_NAME if job in _FAST_QUEUE_JOBS else BULK_QUEUE_NAME


# Job base contract (Plan §24.1 / T-269).
JOB_MAX_TRIES = 5
# Exponential backoff base/cap (seconds) with full jitter so retries from many
# jobs do not thunder against a recovering GitHub.
_RETRY_BACKOFF_BASE_SECONDS = 5.0
_RETRY_BACKOFF_CAP_SECONDS = 600.0

# Redis keys holding dead-letter records (capped lists) for manual replay. Each
# job lane has its own list so a billing credit-grant failure is never lost in,
# or confused with, the GitHub export dead-letter stream (Plan §25.6 T-293).
GH_DEAD_LETTER_KEY = "gh:deadletter"
BILLING_DEAD_LETTER_KEY = "billing:deadletter"
LLM_BATCH_DEAD_LETTER_KEY = "llm:batch:deadletter"
# Back-compat alias: the GitHub key kept its original name for any external
# replay tooling that referenced it.
DEAD_LETTER_KEY = GH_DEAD_LETTER_KEY
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
    queue_name: str | None = None,
    pool: ArqRedis | None = None,
    **kwargs: Any,
) -> str | None:
    """Enqueue a worker job, failing closed if the queue is unreachable.

    ``job_id`` is the idempotency key (the outbound ``push_id`` /
    ``increment_id``): arq drops a duplicate enqueue for a job id already
    queued/in-flight, returning ``None``, so re-submitting an export does not
    start a second push.

    ``queue_name`` overrides the job's home queue; when omitted it is resolved
    from the job name via :func:`queue_for_job` (the F5 fast/bulk split), so
    callers never have to know which lane a job belongs to.

    Raises :class:`QueueUnavailableError` if the Redis-backed queue cannot be
    reached — the caller surfaces a 503, never an inline fallback.
    """
    target_queue = queue_name or queue_for_job(job)
    try:
        arq_pool = pool or await get_arq_pool()
        job_def = await arq_pool.enqueue_job(
            job,
            *args,
            _job_id=job_id,
            _defer_by=defer_by,
            _queue_name=target_queue,
            **kwargs,
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
    dead_letter_key: str,
) -> None:
    """Append a dead-letter record to the given Redis list for manual replay.

    ``dead_letter_key`` routes the record to the per-lane list (``gh:deadletter``
    for GitHub jobs, ``billing:deadletter`` for billing jobs) so the two streams
    stay separate. Stores only the job name, id, sanitized args, and the error
    class name — never tokens, secrets, or raw payloads (Plan §24.10 / §25.6).
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
        await pool.lpush(dead_letter_key, record)
        await pool.ltrim(dead_letter_key, 0, _DEAD_LETTER_MAX - 1)
    except Exception:  # pragma: no cover — best-effort; never mask the failure
        logger.error("queue.dead_letter_persist_failed", job=job)


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

# A special handler short-circuits the dead-letter path for a specific exception
# type, receiving (ctx, name, args, kwargs, exc). Used for GitHub throttling.
SpecialHandler = Callable[
    [dict[str, Any], str, tuple[Any, ...], dict[str, Any], BaseException],
    Awaitable[None],
]


def make_job_wrapper(
    *,
    retries_metric: Counter,
    deadletter_metric: Counter,
    dead_letter_key: str,
    special_handlers: dict[type[BaseException], SpecialHandler] | None = None,
    log_event_prefix: str = "job",
) -> Callable[[str], Callable[[F], F]]:
    """Build a job-decorator factory sharing the durable base contract.

    The single, parameterised implementation behind both ``github_job`` and
    ``billing_job`` (Plan §25.6 T-293). On a transient failure the job retries
    with exponential backoff + jitter (incrementing ``retries_metric``) up to
    :data:`JOB_MAX_TRIES`; after the cap it is dead-lettered to ``dead_letter_key``
    (record + alert log + ``deadletter_metric``) and the exception is swallowed so
    arq does not retry forever. Idempotency/resume is the job body's
    responsibility (jobs are keyed by their argument id and must not duplicate
    side effects on re-run).

    ``special_handlers`` maps an exception type → an async handler invoked
    **before** the generic Exception/dead-letter path, so a registered exception
    (e.g. ``GitHubThrottledError``) can requeue off the try budget rather than
    counting toward dead-lettering. This is the load-bearing distinction that a
    naive ``github_job = generic(fn)`` would lose.
    """
    handlers = special_handlers or {}
    handled_types = tuple(handlers)

    def job_decorator(name: str) -> Callable[[F], F]:
        def wrap(fn: F) -> F:
            @functools.wraps(fn)
            async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
                job_try = int(ctx.get("job_try", 1) or 1)
                try:
                    return await fn(ctx, *args, **kwargs)
                except Retry:
                    raise
                except handled_types as exc:
                    # Backpressure, not failure: a registered handler requeues the
                    # job (deferred, off the dead-letter try budget) instead of
                    # consuming it. Resolve by isinstance so a subclass still maps
                    # to its handler.
                    handler = next(h for t, h in handlers.items() if isinstance(exc, t))
                    await handler(ctx, name, args, kwargs, exc)
                    return None
                except Exception as exc:
                    error = type(exc).__name__
                    if job_try >= JOB_MAX_TRIES:
                        deadletter_metric.labels(job=name).inc()
                        logger.error(
                            f"{log_event_prefix}.deadlettered",
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
                            dead_letter_key=dead_letter_key,
                        )
                        # Swallow so arq marks the job finished (dead-lettered),
                        # not re-queued indefinitely. Manual replay re-enqueues by id.
                        return None
                    retries_metric.labels(job=name).inc()
                    logger.warning(
                        f"{log_event_prefix}.retry",
                        job=name,
                        attempt=job_try,
                        error=error,
                    )
                    raise Retry(defer=_retry_backoff_seconds(job_try)) from exc

            return wrapper  # type: ignore[return-value]

        return wrap

    return job_decorator


# GitHub job lane — preserves the throttle special-case (requeue-not-deadletter)
# and the gh:deadletter routing + github.job.* log events exactly (T-293 / R6).
github_job = make_job_wrapper(
    retries_metric=GITHUB_JOB_RETRIES_TOTAL,
    deadletter_metric=GITHUB_JOB_DEADLETTERED_TOTAL,
    dead_letter_key=GH_DEAD_LETTER_KEY,
    special_handlers={GitHubThrottledError: _requeue_throttled},
    log_event_prefix="github.job",
)

# Billing job lane — no special handlers (billing jobs never throttle on the
# GitHub governor); failures retry then dead-letter to billing:deadletter.
billing_job = make_job_wrapper(
    retries_metric=BILLING_JOB_RETRIES_TOTAL,
    deadletter_metric=BILLING_JOB_DEADLETTERED_TOTAL,
    dead_letter_key=BILLING_DEAD_LETTER_KEY,
    special_handlers=None,
    log_event_prefix="billing.job",
)

# LLM batch job lane (Phase 3 — issue #26) — deferred batch submit/collect.
# Same retry/dead-letter contract; its own ``llm:batch:deadletter`` list so a
# stuck eval batch is never confused with a GitHub export or billing grant.
llm_batch_job = make_job_wrapper(
    retries_metric=LLM_BATCH_JOB_RETRIES_TOTAL,
    deadletter_metric=LLM_BATCH_JOB_DEADLETTERED_TOTAL,
    dead_letter_key=LLM_BATCH_DEAD_LETTER_KEY,
    special_handlers=None,
    log_event_prefix="llm_batch.job",
)

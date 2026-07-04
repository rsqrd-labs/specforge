"""Durable background worker (Phase 21 — T-269; F5 live-queue split).

SpecForge's background-job processes that run work *outside* FastAPI. Since the
F5 scalability remediation there are **two lanes**, each a separate process:

  - ``arq worker.WorkerSettings``      — the BULK lane (arq's default queue):
    high-volume, latency-tolerant GitHub bulk I/O + LLM eval batch jobs.
  - ``arq worker.FastWorkerSettings``  — the FAST lane (a dedicated queue):
    latency-sensitive, money-/user-visible paid credit grants + the PR status
    check, so a bulk-export storm can never occupy their job slots.

Both are stateless and horizontally scalable to N replicas — jobs are
idempotent/checkpointed, and arq dedups crons per queue so each cron fires once
per lane regardless of replica count. The producer/consumer split is single-
sourced by ``services.queue.queue_for_job`` so routing can never drift.

Job roster (registered here as the single source of truth):

  - ``export_push``      — push a workspace to GitHub.               [bulk]
  - ``reconcile_event``  — apply an inbound webhook (T-272).         [bulk]
  - ``backfill_repo``    — reconcile missed events (T-273).          [bulk]
  - ``increment_push``   — push an increment delta (T-279/T-280).    [bulk]
  - ``projects_sync``    — sync the Projects v2 board (T-281).       [bulk]
  - ``llm_batch_*``      — deferred eval batch submit/collect.       [bulk]
  - ``pr_check``         — post the SpecForge status check (T-282).  [fast]
  - ``billing_process_webhook`` — grant credits from a Lemon event.  [fast]

Every job carries the shared base contract from ``services.queue`` (idempotency
keying, exponential backoff + jitter retries to ``JOB_MAX_TRIES``, then a
dead-letter record + metric + alert). The handlers for jobs owned by later tasks
lazily import their service module so the worker boots today; no producer
enqueues them until their task lands.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sentry_sdk
import structlog
from arq import cron

from config import settings
from services.queue import (
    BULK_QUEUE_NAME,
    FAST_QUEUE_NAME,
    JOB_MAX_TRIES,
    _redis_settings,
    billing_job,
    close_arq_pool,
    github_job,
    llm_batch_job,
)

logger = structlog.get_logger(__name__)

# Bounded global concurrency so a flood of jobs cannot exhaust the worker's DB
# pool / sockets; per-tenant fairness (the per-installation governor) is T-274.
_MAX_JOBS = 20
# The fast lane (F5) does light, quick work (a webhook grant + a PR status post),
# so it runs fewer jobs concurrently than the bulk lane. This also caps its peak
# DB-connection draw — adding the fast worker process therefore adds far less
# than a full per-process pool to the Postgres connection footprint (RUNBOOK §15
# deploy prerequisite). Per-process pool size itself is DB_POOL_SIZE-tunable.
_FAST_MAX_JOBS = 10
# Hard ceiling on a single job's wall-clock (a large export of many issues).
_JOB_TIMEOUT_SECONDS = 1800
# Do NOT retain job results. Status is polled from the DB push row, not from
# arq's result key — and a retained result key under a stable _job_id (push_id)
# would make arq drop a *re-export* of the same push as a duplicate (it dedups on
# the job OR result key), silently never running it. With keep_result=0 the keys
# clear on completion, so re-export re-enqueues while the in-flight job key still
# guards against concurrent double-submits.
_KEEP_RESULT_SECONDS = 0
# Periodic drift reconciliation interval (minutes).
_DRIFT_CRON_MINUTES = {0, 15, 30, 45}
# Daily webhook-idempotency retention purge — off-peak, off the top of the hour
# so it never coincides with a drift-reconcile tick.
_PURGE_CRON_HOUR = {3}
_PURGE_CRON_MINUTE = {17}

# Billing crons (Phase 22 — T-298). The 60s sweep recovers queue outages and
# crashed-worker rows; billing_reconcile is the 15-minute backstop staggered off
# the GitHub drift ticks ({0,15,30,45}) and the purges; the billing purge runs
# off-peak and clear of every other tick.
_BILLING_SWEEP_CRON_SECOND = {0}
_BILLING_RECONCILE_CRON_MINUTE = {7, 22, 37, 52}
_BILLING_PURGE_CRON_HOUR = {3}
_BILLING_PURGE_CRON_MINUTE = {42}

# LLM batch eval sweep (Phase 3 — issue #26). Runs every minute, staggered off
# the billing 60s sweep ({0}) so the two don't fire on the same second. Batches
# take minutes to ~24h; a per-minute poll is ample and the provider retrieve is
# cheap.
_LLM_BATCH_SWEEP_CRON_SECOND = {30}

# Generation-ETA rollup (issue #21 Phase 2b). Every 10 minutes on a minute set
# that collides with no other tick (drift {0,15,30,45}, billing reconcile
# {7,22,37,52}, purges at the top-of-hour offsets). 10-minute cadence under the
# 15-minute cache TTL guarantees the cached estimates never expire while the
# worker is healthy; the startup run warms the cache right after a deploy.
_GENERATION_ESTIMATES_CRON_MINUTE = {3, 13, 23, 33, 43, 53}

# Per-queue backpressure sampler (F5). Fires every minute at :45 — a second that
# collides with no other tick (billing sweep {0}, llm batch {30}) — on BOTH
# worker classes, each sampling only the queue IT consumes. This is per-queue
# work, so running it on both lanes is correct (not a double-fire): a fast
# replica samples the fast queue, a bulk replica samples the bulk queue.
_QUEUE_SAMPLE_CRON_SECOND = {45}

# Data retention & purging (issue #43). All BULK-lane global crons — registered on
# exactly one class (F5 rule) so they never double-fire. The size sampler runs
# hourly at :41 (clear of every minute-set above); the three tier purges run
# off-peak at 4:11 / 4:31 / 4:51 — each clear of the drift {0,15,30,45}, billing
# reconcile {7,22,37,52}, generation-estimate {3,13,23,33,43,53}, and the 3:17/3:42
# purge ticks (plan §1.5 collision-free cron map).
_TABLE_STATS_CRON_MINUTE = {41}
_RETENTION_TIER1_CRON_HOUR = {4}
_RETENTION_TIER1_CRON_MINUTE = {11}
_RETENTION_TIER2_CRON_HOUR = {4}
_RETENTION_TIER2_CRON_MINUTE = {31}
_RETENTION_TIER3_CRON_HOUR = {4}
_RETENTION_TIER3_CRON_MINUTE = {51}


@github_job("export_push")
async def export_push(
    ctx: dict[str, Any],
    push_id: str,
    repo_name: str,
    visibility: str,
) -> None:
    """Push a prepared workspace export to GitHub (idempotent, resumable)."""
    from database import AsyncSessionLocal
    from services.pipeline import github_export_service

    async with AsyncSessionLocal() as db:
        await github_export_service.run_export_push(
            UUID(push_id), repo_name, visibility, db=db
        )


@github_job("reconcile_event")
async def reconcile_event(
    ctx: dict[str, Any],
    delivery_id: str,
    event_type: str,
    raw: bytes,
) -> None:
    """Apply a verified inbound webhook delivery (implemented in T-272)."""
    from services.integrations import github_reconcile

    await github_reconcile.reconcile_event(ctx, delivery_id, event_type, raw)


@github_job("backfill_repo")
async def backfill_repo(ctx: dict[str, Any], push_id: str) -> None:
    """Reconcile missed events from the issues API (implemented in T-273)."""
    from services.integrations import github_reconcile

    await github_reconcile.backfill_repo(ctx, push_id)


@github_job("increment_push")
async def increment_push(ctx: dict[str, Any], increment_id: str) -> None:
    """Push an increment delta to GitHub (implemented in T-279/T-280)."""
    from services.pipeline import increment_service

    await increment_service.run_increment_push(ctx, increment_id)


@github_job("projects_sync")
async def projects_sync(ctx: dict[str, Any], push_id: str) -> None:
    """Sync the Projects v2 board + milestones (implemented in T-281)."""
    from services.integrations import github_projects

    await github_projects.sync_board(ctx, push_id)


@github_job("pr_check")
async def pr_check(
    ctx: dict[str, Any], push_id: str, pr_number: int, trigger: str = "auto"
) -> None:
    """Post the SpecForge PR status check (implemented in T-282).

    ``trigger`` (``auto``/``manual``, default ``auto``) is supplied by the
    reconcile router (issue #27 Phase 4); the default keeps an older in-flight
    job enqueued with 3 positional args on its pre-Phase-4 ``auto`` meaning.
    """
    from services.integrations import pr_evaluator

    await pr_evaluator.run_pr_check(ctx, push_id, pr_number, trigger)


@github_job("reconcile_drift")
async def reconcile_drift(ctx: dict[str, Any]) -> None:
    """Periodic: recompute drift and catch events missed while down (T-273)."""
    from services.integrations import github_reconcile

    await github_reconcile.reconcile_drift(ctx)


async def purge_webhook_events(ctx: dict[str, Any]) -> None:
    """Daily: bound the webhook idempotency tables' growth (retention purge).

    Not wrapped in the ``github_job`` retry/dead-letter contract: a transient
    failure is harmless because the 30-day retention window makes a missed daily
    run inconsequential, and the next cron tick retries. Exceptions are caught
    and logged so a blip never surfaces as a worker error.
    """
    from database import AsyncSessionLocal
    from services.maintenance import purge_expired_webhook_events

    try:
        async with AsyncSessionLocal() as db:
            await purge_expired_webhook_events(db)
    except Exception:  # pragma: no cover — best-effort; next daily tick retries
        logger.exception("maintenance.webhook_events_purge_failed")


@billing_job("billing_process_webhook")
async def billing_process_webhook(ctx: dict[str, Any], webhook_event_id: str) -> None:
    """Process one Lemon webhook inbox row exactly once (implemented in T-298).

    Wrapped in the ``billing_job`` contract: a failure persisted by the body is
    re-raised here so the wrapper retries with backoff, then dead-letters to
    ``billing:deadletter`` after ``JOB_MAX_TRIES``.
    """
    from services import billing_worker

    await billing_worker.billing_process_webhook(ctx, webhook_event_id)


@llm_batch_job("llm_batch_submit")
async def llm_batch_submit(ctx: dict[str, Any], batch_job_id: str) -> None:
    """Create the provider batch for a pending eval row (Phase 3 — issue #26).

    Wrapped in the ``llm_batch_job`` contract: a transient provider error retries
    with backoff, then dead-letters to ``llm:batch:deadletter`` after
    ``JOB_MAX_TRIES``. Idempotent — a no-op once the row is submitted or gone.
    """
    from services.evals import eval_batch

    await eval_batch.run_submit(ctx, batch_job_id)


@llm_batch_job("llm_batch_collect")
async def llm_batch_collect(ctx: dict[str, Any], batch_job_id: str) -> None:
    """Poll a submitted eval batch and persist its result once ended (Phase 3).

    Returns cleanly while the batch is still processing (the sweep cron re-enqueues
    it next tick); a transient poll/fetch error retries then dead-letters.
    """
    from services.evals import eval_batch

    await eval_batch.run_collect(ctx, batch_job_id)


async def llm_batch_sweep(ctx: dict[str, Any]) -> None:
    """Cron: recover stuck pending eval batches and advance submitted ones (T-3).

    Plain cron — the body catches and logs; a transient blip is recovered by the
    next tick, so a failure must never surface as a worker error.
    """
    from services.evals import eval_batch

    await eval_batch.sweep(ctx)


async def refresh_generation_estimates(ctx: dict[str, Any]) -> None:
    """Cron (10m): roll the latency ledger up into the cached generation-ETA
    estimates served by GET /stages/generation-estimates (issue #21 Phase 2b).

    Plain cron — the body catches and logs; a transient blip is recovered by the
    next tick, so a failure must never surface as a worker error.
    """
    from services.llm import generation_estimates

    await generation_estimates.refresh_generation_estimates(ctx)


async def billing_process_pending_webhooks(ctx: dict[str, Any]) -> None:
    """Cron (60s): recover queue-outage + crashed-worker inbox rows (T-298).

    Plain cron — the body catches and logs; a transient blip is recovered by the
    next tick, so a failure must never surface as a worker error.
    """
    from services import billing_worker

    await billing_worker.billing_process_pending_webhooks(ctx)


async def billing_reconcile(ctx: dict[str, Any]) -> None:
    """Cron (15m): reconciliation backstop — Lane 1 inbox replay (T-298/T-301)."""
    from services import billing_worker

    await billing_worker.billing_reconcile(ctx)


async def purge_billing_events(ctx: dict[str, Any]) -> None:
    """Cron (daily): bound the billing inbox + terminal checkout attempts (T-298)."""
    from services import billing_worker

    await billing_worker.purge_billing_events(ctx)


async def sample_table_stats(ctx: dict[str, Any]) -> None:
    """Cron (hourly): publish the retention size baseline (issue #43, Phase 0).

    Read-only, zero risk — samples ``pg_total_relation_size`` + ``n_live_tup`` for
    the fixed table allowlist into gauges. Gated on the master ``retention_enabled``
    AND ``retention_table_stats_enabled`` (plan §8: retention_enabled=false disables
    the sampler too). Plain cron — the body catches and logs; a metrics blip must
    never surface as a worker error.
    """
    if not (settings.retention_enabled and settings.retention_table_stats_enabled):
        return
    from database import AsyncSessionLocal
    from services import retention

    try:
        async with AsyncSessionLocal() as db:
            await retention.sample_table_stats(db)
    except Exception:  # pragma: no cover — best-effort; next hourly tick retries
        logger.exception("retention.table_stats_failed")


async def retention_tier1_purge(ctx: dict[str, Any]) -> None:
    """Cron (daily 4:11 UTC): Tier-1 telemetry TTL + failed-row purges (issue #43).

    Gated on the master ``retention_enabled``; each job further honours dry-run and
    its own tier flag. Plain cron — a missed daily run is inconsequential (the next
    tick retries) so the body catches and logs rather than surfacing an error.
    """
    if not settings.retention_enabled:
        return
    from database import AsyncSessionLocal
    from services import retention

    try:
        async with AsyncSessionLocal() as db:
            await retention.run_tier1(db)
    except Exception:  # pragma: no cover — best-effort; next daily tick retries
        logger.exception("retention.tier1_purge_failed")


async def retention_tier2_purge(ctx: dict[str, Any]) -> None:
    """Cron (daily 4:31 UTC): Tier-2 stage-version/storyboard keep-N (issue #43)."""
    if not settings.retention_enabled:
        return
    from database import AsyncSessionLocal
    from services import retention

    try:
        async with AsyncSessionLocal() as db:
            await retention.run_tier2(db)
    except Exception:  # pragma: no cover — best-effort; next daily tick retries
        logger.exception("retention.tier2_purge_failed")


async def retention_tier3_purge(ctx: dict[str, Any]) -> None:
    """Cron (daily 4:51 UTC): Tier-3 trashed-workspace hard-delete (issue #43)."""
    if not settings.retention_enabled:
        return
    from database import AsyncSessionLocal
    from services import retention

    try:
        async with AsyncSessionLocal() as db:
            await retention.purge_trashed_workspaces(db)
    except Exception:  # pragma: no cover — best-effort; next daily tick retries
        logger.exception("retention.tier3_purge_failed")


async def _on_startup(ctx: dict[str, Any]) -> None:
    """Initialise worker-process services: logging, Sentry, the shared Redis client.

    ``configure_logging()`` is run here (T-284) because the worker is a separate
    process that never goes through the FastAPI ``setup_observability`` path: it
    installs the structlog redaction processor + the stdlib ``SensitiveDataFilter``
    so worker audit rows (export/PR/check/increment/reconcile) are structured and
    never leak a token or key. Sentry runs on the worker (Plan §24.10) so
    background-job failures are captured. The shared Redis client is registered so
    services that resolve it outside a request reuse one pool.
    """
    from services.observability import configure_logging

    configure_logging()
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.0,
        )
    from database import _initialize_redis, build_redis_client

    # Use the single bounded/health-checked Redis factory (F8) — the worker now
    # scales to N replicas (F5), so an unbounded per-process pool here would
    # multiply Redis connections the same way the API path did before F8.
    _initialize_redis(build_redis_client())
    queue = getattr(ctx.get("redis"), "default_queue_name", "unknown")
    logger.info("worker.started", queue=queue, max_jobs=_MAX_JOBS)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    await close_arq_pool()


async def sample_queue_stats(ctx: dict[str, Any]) -> None:
    """Cron: publish THIS worker's queue depth + oldest-job age (F5 backpressure).

    Sampled from a cron rather than on_job_start because a STALLED queue starts
    no jobs — an on-job-start gauge would read stale (or never update) exactly
    when the alert must fire. Each worker samples only the queue it consumes
    (``ctx['redis'].default_queue_name``), so the fast and bulk lanes are
    independently visible and a missing fast worker shows as a climbing
    ``specforge_worker_queue_oldest_age_seconds{queue="arq:queue:fast"}``.

    Reads the queue's Redis sorted-set directly (zcard for depth, the lowest
    score for the oldest ready job) rather than fetching every job definition, so
    the sample stays O(log n) even on a deep backlog. Plain cron — the body
    catches and logs; a metrics blip must never surface as a worker error.
    """
    import time

    from services.observability import GITHUB_QUEUE_DEPTH, record_worker_queue_stats

    try:
        redis = ctx["redis"]
        queue = getattr(redis, "default_queue_name", BULK_QUEUE_NAME)
        depth = await redis.zcard(queue)
        oldest_age_seconds = 0.0
        oldest = await redis.zrange(queue, 0, 0, withscores=True)
        if oldest:
            # arq scores a ready job with its enqueue time (ms); a deferred job
            # with its future run time, so its age clamps to 0 (not yet waiting).
            score_ms = float(oldest[0][1])
            oldest_age_seconds = max(0.0, (time.time() * 1000 - score_ms) / 1000)
        record_worker_queue_stats(queue, int(depth), oldest_age_seconds)
        # Back-compat: the pre-split gauge maps to the bulk (GitHub) queue.
        if queue == BULK_QUEUE_NAME:
            GITHUB_QUEUE_DEPTH.set(int(depth))
    except Exception:  # pragma: no cover — never let metrics break the worker
        logger.debug("worker.queue_stats_unavailable")


def _queue_sampler_cron():
    """The per-queue backpressure sampler — runs on BOTH lanes (see F5 note).

    It is per-queue work (each worker samples only the queue it consumes), so
    registering it on both WorkerSettings classes is correct, not a double-fire.
    A fresh ``cron(...)`` object per class keeps each lane's scheduling state
    independent.
    """
    return cron(
        sample_queue_stats,
        second=_QUEUE_SAMPLE_CRON_SECOND,
        run_at_startup=True,
    )


class _BaseWorkerSettings:
    """Shared worker config for both lanes (F5).

    The two lanes are separate PROCESSES — separate event loops, DB pools, and
    arq job-slot budgets — so a bulk-export storm cannot occupy the fast lane's
    slots. Everything except the queue name, function roster, and cron set is
    identical, so it lives here once.

    arq's CLI introspects ``settings_cls.__dict__`` directly (``get_kwargs`` in
    ``arq.worker``) and never walks the MRO, so attributes left only on this
    base class are INVISIBLE to ``arq worker.WorkerSettings`` — both lanes
    would silently boot on arq defaults (localhost Redis, no startup hook, no
    job limits). ``__init_subclass__`` therefore materialises every shared
    attribute into each subclass's own namespace at class-creation time; a
    subclass override (e.g. the fast lane's ``max_jobs``) still wins.
    """

    redis_settings = _redis_settings()
    max_jobs = _MAX_JOBS
    max_tries = JOB_MAX_TRIES
    job_timeout = _JOB_TIMEOUT_SECONDS
    keep_result = _KEEP_RESULT_SECONDS
    on_startup = _on_startup
    on_shutdown = _on_shutdown

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, value in _BaseWorkerSettings.__dict__.items():
            if not name.startswith("_") and name not in cls.__dict__:
                setattr(cls, name, value)


class WorkerSettings(_BaseWorkerSettings):
    """BULK lane — the default queue: ``arq worker.WorkerSettings``.

    Drains the high-volume, latency-tolerant GitHub bulk I/O and the LLM eval
    batch jobs, plus their crons. Kept on arq's DEFAULT queue so any job enqueued
    before the F5 split still drains here (nothing stranded at the cutover).
    Crons here are GLOBAL (drift, purges, batch sweep, estimates) so each is
    registered on EXACTLY this one class — arq dedups a cron per queue across
    replicas, so registering it on both lanes would fire it twice.
    """

    queue_name = BULK_QUEUE_NAME
    functions = [
        export_push,
        reconcile_event,
        backfill_repo,
        increment_push,
        projects_sync,
        llm_batch_submit,
        llm_batch_collect,
    ]
    cron_jobs = [
        cron(reconcile_drift, minute=_DRIFT_CRON_MINUTES, run_at_startup=False),
        cron(
            purge_webhook_events,
            hour=_PURGE_CRON_HOUR,
            minute=_PURGE_CRON_MINUTE,
            run_at_startup=False,
        ),
        cron(
            llm_batch_sweep,
            second=_LLM_BATCH_SWEEP_CRON_SECOND,
            run_at_startup=False,
        ),
        cron(
            refresh_generation_estimates,
            minute=_GENERATION_ESTIMATES_CRON_MINUTE,
            run_at_startup=True,
        ),
        # Data retention (issue #43) — BULK-lane global crons, one class only.
        cron(
            sample_table_stats,
            minute=_TABLE_STATS_CRON_MINUTE,
            run_at_startup=False,
        ),
        cron(
            retention_tier1_purge,
            hour=_RETENTION_TIER1_CRON_HOUR,
            minute=_RETENTION_TIER1_CRON_MINUTE,
            run_at_startup=False,
        ),
        cron(
            retention_tier2_purge,
            hour=_RETENTION_TIER2_CRON_HOUR,
            minute=_RETENTION_TIER2_CRON_MINUTE,
            run_at_startup=False,
        ),
        cron(
            retention_tier3_purge,
            hour=_RETENTION_TIER3_CRON_HOUR,
            minute=_RETENTION_TIER3_CRON_MINUTE,
            run_at_startup=False,
        ),
        _queue_sampler_cron(),
    ]


class FastWorkerSettings(_BaseWorkerSettings):
    """FAST lane — ``arq worker.FastWorkerSettings``.

    Drains the latency-sensitive, money-/user-visible jobs (paid credit grants
    and the PR status check) on a dedicated queue so a bulk-export storm can
    never occupy their job slots. The billing recovery crons live here too, as
    the billing domain's home lane. DEPLOY INVARIANT: this process MUST run in
    every environment, or paid credit grants never drain (RUNBOOK §16).
    """

    queue_name = FAST_QUEUE_NAME
    max_jobs = _FAST_MAX_JOBS  # lighter concurrency than the bulk lane (footprint)
    functions = [
        billing_process_webhook,
        pr_check,
    ]
    cron_jobs = [
        cron(
            billing_process_pending_webhooks,
            second=_BILLING_SWEEP_CRON_SECOND,
            run_at_startup=False,
        ),
        cron(
            billing_reconcile,
            minute=_BILLING_RECONCILE_CRON_MINUTE,
            run_at_startup=False,
        ),
        cron(
            purge_billing_events,
            hour=_BILLING_PURGE_CRON_HOUR,
            minute=_BILLING_PURGE_CRON_MINUTE,
            run_at_startup=False,
        ),
        _queue_sampler_cron(),
    ]

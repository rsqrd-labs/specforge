"""Durable background worker (Phase 21 — T-269).

SpecForge's first process that runs work *outside* FastAPI. Started with
``arq worker.WorkerSettings`` (see ``docker-compose.yml`` / ``Procfile``), it
drives every GitHub write/sync job off the request path.

Job roster (registered here as the single source of truth; producers come
online across Phase 21):

  - ``export_push``      — push a workspace to GitHub (fully implemented here).
  - ``reconcile_event``  — apply an inbound webhook (T-272).
  - ``backfill_repo``    — reconcile missed events from the issues API (T-273).
  - ``increment_push``   — push an increment delta (T-279/T-280).
  - ``projects_sync``    — sync the Projects v2 board (T-281).
  - ``pr_check``         — post the SpecForge status check (T-282).
  - ``reconcile_drift``  — periodic cron that recomputes drift / catches missed
    events (T-273).

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
from services.observability import GITHUB_QUEUE_DEPTH
from services.queue import (
    JOB_MAX_TRIES,
    _redis_settings,
    close_arq_pool,
    github_job,
)

logger = structlog.get_logger(__name__)

# Bounded global concurrency so a flood of jobs cannot exhaust the worker's DB
# pool / sockets; per-tenant fairness (the per-installation governor) is T-274.
_MAX_JOBS = 20
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
async def pr_check(ctx: dict[str, Any], push_id: str, pr_number: int) -> None:
    """Post the SpecForge PR status check (implemented in T-282)."""
    from services.integrations import pr_evaluator

    await pr_evaluator.run_pr_check(ctx, push_id, pr_number)


@github_job("reconcile_drift")
async def reconcile_drift(ctx: dict[str, Any]) -> None:
    """Periodic: recompute drift and catch events missed while down (T-273)."""
    from services.integrations import github_reconcile

    await github_reconcile.reconcile_drift(ctx)


async def _on_startup(ctx: dict[str, Any]) -> None:
    """Initialise worker-process services: Sentry, the shared Redis client.

    Sentry runs on the worker (Plan §24.10) so background-job failures are
    captured. The shared Redis client is registered so services that resolve it
    outside a request (the token provider in ``run_export_push``) reuse one pool.
    """
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.0,
        )
    from redis.asyncio import Redis

    from database import _initialize_redis

    _initialize_redis(Redis.from_url(settings.redis_url, decode_responses=True))
    logger.info("github.worker.started", max_jobs=_MAX_JOBS)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    await close_arq_pool()


async def _on_job_start(ctx: dict[str, Any]) -> None:
    """Surface approximate queue depth as a gauge for backpressure alerts."""
    try:
        depth = await ctx["redis"].queued_jobs()
        GITHUB_QUEUE_DEPTH.set(len(depth))
    except Exception:  # pragma: no cover — never let metrics break a job
        logger.debug("github.worker.queue_depth_unavailable")


class WorkerSettings:
    """arq worker entrypoint: ``arq worker.WorkerSettings``."""

    functions = [
        export_push,
        reconcile_event,
        backfill_repo,
        increment_push,
        projects_sync,
        pr_check,
    ]
    cron_jobs = [
        cron(
            reconcile_drift,
            minute=_DRIFT_CRON_MINUTES,
            run_at_startup=False,
        )
    ]
    redis_settings = _redis_settings()
    max_jobs = _MAX_JOBS
    max_tries = JOB_MAX_TRIES
    job_timeout = _JOB_TIMEOUT_SECONDS
    keep_result = _KEEP_RESULT_SECONDS
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    on_job_start = _on_job_start

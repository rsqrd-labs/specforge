"""Drain paid-generation jobs with the deterministic browser-E2E provider.

The browser API and the generation worker are separate processes in production,
so the E2E stack must exercise the same boundary.  Importing and installing the
test overrides in this process keeps provider calls zero-network while ARQ,
Redis, checkpoints, persistence, and SSE observation remain real.
"""

from __future__ import annotations

import asyncio

from arq.worker import create_worker

from scripts.run_frontend_e2e_server import install_deterministic_overrides


async def _run() -> None:
    install_deterministic_overrides()

    # Import after installing the overrides. ``stage_generate`` imports the
    # stage manager lazily, and this preserves the deterministic adapter in the
    # worker process instead of resolving the fake CI provider credentials.
    import worker as worker_module
    from worker import WorkerSettings

    # Production drains stage generation from the existing bulk worker, so the
    # E2E stack runs that exact class. Drop the unrelated periodic work (drift
    # reconcile, purges, batch sweeps) but KEEP the readiness heartbeat: the API
    # gates paid generation on it, and a single boot-time publish would expire
    # after GENERATION_WORKER_HEARTBEAT_TTL_SECONDS and take the E2E journeys
    # down with it in any environment where readiness is enforced.
    heartbeat_crons = [
        job
        for job in WorkerSettings.cron_jobs
        if job.coroutine is worker_module.generation_worker_heartbeat
    ]
    assert heartbeat_crons, "bulk lane lost its generation-worker heartbeat cron"
    generation_worker = create_worker(WorkerSettings, cron_jobs=heartbeat_crons)
    try:
        await generation_worker.async_run()
    finally:
        await generation_worker.close()


if __name__ == "__main__":
    asyncio.run(_run())

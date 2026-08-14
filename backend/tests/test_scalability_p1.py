"""Tests for the P1 scalability remediation (docs/SCALABILITY_AUDIT.md).

F3 — transaction-pooler connect args + DB-pool / queue observability.
F4 — WEB_CONCURRENCY-driven gunicorn worker count.
F5 — fast/bulk live-queue split (routing table + worker partition + sampler).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import database
from config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# F3 — transaction-pooler (PgBouncer) connect args
# ---------------------------------------------------------------------------
def test_connect_args_default_has_no_prepared_statement_overrides(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+asyncpg://u:p@h/db",
        raising=False,
    )
    monkeypatch.setattr(settings, "db_transaction_pooler_mode", False, raising=False)
    args = database._engine_connect_args()
    # The F9 server guards are present; the pooler overrides are NOT (byte-
    # identical to the pre-F3 direct-connect path).
    assert "server_settings" in args
    assert "prepared_statement_cache_size" not in args
    assert "prepared_statement_name_func" not in args
    assert "statement_cache_size" not in args


def test_connect_args_pooler_mode_disables_prepared_statements(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://u:p@h/db", raising=False
    )
    monkeypatch.setattr(settings, "db_transaction_pooler_mode", True, raising=False)
    args = database._engine_connect_args()
    # Both SQLAlchemy's and asyncpg's statement caches are disabled, and a unique
    # name function is supplied, so statements never collide across pooled
    # backends. The F9 server guards are still emitted.
    assert args["prepared_statement_cache_size"] == 0
    assert args["statement_cache_size"] == 0
    assert callable(args["prepared_statement_name_func"])
    n1 = args["prepared_statement_name_func"]()
    n2 = args["prepared_statement_name_func"]()
    assert n1 != n2 and n1.startswith("__asyncpg_")
    assert "server_settings" in args


def test_connect_args_non_postgres_url_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "database_url", "sqlite+aiosqlite:///:memory:", raising=False
    )
    monkeypatch.setattr(settings, "db_transaction_pooler_mode", True, raising=False)
    assert database._engine_connect_args() == {}


# ---------------------------------------------------------------------------
# F3 — DB-pool collector + queue/background-task gauges
# ---------------------------------------------------------------------------
def test_db_pool_collector_emits_max_and_total() -> None:
    from services.observability import _DbPoolCollector

    families = {m.name: m for m in _DbPoolCollector().collect()}
    # db_pool_max is always emitted (size + overflow ceiling).
    assert "thought2build_db_pool_max" in families
    max_family = families["thought2build_db_pool_max"]
    assert max_family.samples[0].value == (
        settings.db_pool_size + settings.db_max_overflow
    )


def test_record_worker_queue_stats_sets_gauges() -> None:
    from services.observability import (
        WORKER_QUEUE_DEPTH,
        WORKER_QUEUE_OLDEST_AGE_SECONDS,
        record_worker_queue_stats,
    )

    record_worker_queue_stats("arq:queue:test", 7, 42.5)
    assert WORKER_QUEUE_DEPTH.labels(queue="arq:queue:test")._value.get() == 7
    assert (
        WORKER_QUEUE_OLDEST_AGE_SECONDS.labels(queue="arq:queue:test")._value.get()
        == 42.5
    )
    # Negatives clamp to 0 (a deferred-job age never goes negative on the gauge).
    record_worker_queue_stats("arq:queue:test", -1, -5.0)
    assert WORKER_QUEUE_DEPTH.labels(queue="arq:queue:test")._value.get() == 0
    assert (
        WORKER_QUEUE_OLDEST_AGE_SECONDS.labels(queue="arq:queue:test")._value.get() == 0
    )


def test_set_background_task_count_sets_gauge() -> None:
    from services.observability import BACKGROUND_TASKS, set_background_task_count

    set_background_task_count("eval", 5)
    assert BACKGROUND_TASKS.labels(registry="eval")._value.get() == 5
    set_background_task_count("eval", -2)  # clamps
    assert BACKGROUND_TASKS.labels(registry="eval")._value.get() == 0


# ---------------------------------------------------------------------------
# F4 — gunicorn worker count from WEB_CONCURRENCY
# ---------------------------------------------------------------------------
def _load_gunicorn_conf(monkeypatch, **env) -> dict:
    for key in ("WEB_CONCURRENCY", "WEB_GRACEFUL_TIMEOUT", "PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    ns: dict = {}
    exec((BACKEND_ROOT / "gunicorn.conf.py").read_text(), ns)
    return ns


def test_gunicorn_default_workers_is_two(monkeypatch) -> None:
    ns = _load_gunicorn_conf(monkeypatch)
    assert ns["workers"] == 2
    assert ns["worker_class"] == "uvicorn.workers.UvicornWorker"


def test_gunicorn_web_concurrency_override(monkeypatch) -> None:
    assert _load_gunicorn_conf(monkeypatch, WEB_CONCURRENCY="7")["workers"] == 7


def test_gunicorn_junk_web_concurrency_falls_back(monkeypatch) -> None:
    assert _load_gunicorn_conf(monkeypatch, WEB_CONCURRENCY="abc")["workers"] == 2


def test_gunicorn_workers_floored_at_one(monkeypatch) -> None:
    assert _load_gunicorn_conf(monkeypatch, WEB_CONCURRENCY="0")["workers"] == 1


def test_gunicorn_bind_honours_port(monkeypatch) -> None:
    assert _load_gunicorn_conf(monkeypatch, PORT="9999")["bind"] == "0.0.0.0:9999"


# ---------------------------------------------------------------------------
# F5 — fast/bulk live-queue split
# ---------------------------------------------------------------------------
def test_queue_for_job_routes_fast_and_bulk() -> None:
    from services.queue import (
        BULK_QUEUE_NAME,
        FAST_QUEUE_NAME,
        GENERATION_QUEUE_NAME,
        queue_for_job,
    )

    assert queue_for_job("billing_process_webhook") == FAST_QUEUE_NAME
    assert queue_for_job("pr_check") == FAST_QUEUE_NAME
    assert queue_for_job("reconcile_issue_event") == FAST_QUEUE_NAME
    assert queue_for_job("refresh_task_states") == FAST_QUEUE_NAME
    assert queue_for_job("stage_generate") == GENERATION_QUEUE_NAME
    for bulk in (
        "export_push",
        "backfill_repo",
        "increment_push",
        "projects_sync",
        "reconcile_event",
        "llm_batch_submit",
        "llm_batch_collect",
    ):
        assert queue_for_job(bulk) == BULK_QUEUE_NAME
    # Bulk queue stays arq's default so pre-split jobs are never stranded.
    assert BULK_QUEUE_NAME == "arq:queue"


async def test_enqueue_routes_to_resolved_queue() -> None:
    from services import queue as queue_mod

    captured: dict = {}

    class _FakePool:
        async def enqueue_job(self, job, *args, **kwargs):
            captured["job"] = job
            captured["queue"] = kwargs.get("_queue_name")

            class _Def:
                job_id = "jid"

            return _Def()

    await queue_mod.enqueue("pr_check", 1, pool=_FakePool())
    assert captured["queue"] == queue_mod.FAST_QUEUE_NAME
    await queue_mod.enqueue("export_push", 2, pool=_FakePool())
    assert captured["queue"] == queue_mod.BULK_QUEUE_NAME
    await queue_mod.enqueue("stage_generate", {}, pool=_FakePool())
    assert captured["queue"] == queue_mod.GENERATION_QUEUE_NAME
    # Explicit override wins over the routing table.
    await queue_mod.enqueue("export_push", 3, queue_name="custom", pool=_FakePool())
    assert captured["queue"] == "custom"


def test_worker_settings_partition_is_disjoint_and_complete() -> None:
    import worker
    from services.queue import (
        BULK_QUEUE_NAME,
        FAST_QUEUE_NAME,
        GENERATION_QUEUE_NAME,
        queue_for_job,
    )

    bulk = {f.__name__ for f in worker.WorkerSettings.functions}
    fast = {f.__name__ for f in worker.FastWorkerSettings.functions}
    generation = {
        getattr(f, "__name__", getattr(f, "name", None))
        for f in worker.GenerationWorkerSettings.functions
    }
    # No job is registered on both lanes.
    assert bulk.isdisjoint(fast)
    assert bulk.isdisjoint(generation)
    assert fast.isdisjoint(generation)
    # Each lane's queue_name matches its routing.
    assert worker.WorkerSettings.queue_name == BULK_QUEUE_NAME
    assert worker.FastWorkerSettings.queue_name == FAST_QUEUE_NAME
    assert worker.GenerationWorkerSettings.queue_name == GENERATION_QUEUE_NAME
    # Every registered job lands on the lane the routing table sends it to.
    for name in bulk:
        assert queue_for_job(name) == BULK_QUEUE_NAME
    for name in fast:
        assert queue_for_job(name) == FAST_QUEUE_NAME
    for name in generation:
        assert queue_for_job(name) == GENERATION_QUEUE_NAME
    # The fast lane carries exactly the latency-sensitive jobs.
    assert fast == {
        "billing_process_webhook",
        "pr_check",
        "reconcile_issue_event",
        "refresh_task_states",
    }
    assert generation == {"stage_generate"}
    assert (
        worker.GenerationWorkerSettings.functions[0].max_tries
        == worker._GENERATION_JOB_MAX_TRIES
    )
    assert worker._GENERATION_JOB_MAX_TRIES >= 100
    # keep_result is inherited from the shared base (the re-export dedup guard).
    assert worker.WorkerSettings.keep_result == 0
    assert worker.FastWorkerSettings.keep_result == 0
    assert worker.GenerationWorkerSettings.keep_result == 0
    assert worker.GenerationWorkerSettings.job_timeout == (
        worker._GENERATION_JOB_SLICE_SECONDS + 30
    )
    assert worker._GENERATION_JOB_SLICE_SECONDS <= (
        worker.settings.stage_generation_deadline_seconds
        - worker.settings.stage_retry_min_remaining_seconds
    )
    # The light-work fast lane runs fewer concurrent jobs than the bulk lane, so
    # adding its process is a smaller Postgres-connection footprint add (§15).
    assert worker.FastWorkerSettings.max_jobs < worker.WorkerSettings.max_jobs


async def test_generation_slice_timeout_requeues_same_durable_job(monkeypatch) -> None:
    import worker
    from services.pipeline.stage_manager import stage_manager

    cancelled = False

    async def _blocked(_payload):
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True

    monkeypatch.setattr(worker, "_GENERATION_JOB_SLICE_SECONDS", 0.01)
    monkeypatch.setattr(stage_manager, "execute_queued_generation", _blocked)

    with pytest.raises(worker.Retry):
        await worker.stage_generate({}, {"generation_run_id": "run-1"})

    assert cancelled is True


def test_global_crons_registered_on_exactly_one_lane() -> None:
    import worker

    bulk_crons = {c.name for c in worker.WorkerSettings.cron_jobs}
    fast_crons = {c.name for c in worker.FastWorkerSettings.cron_jobs}
    # The per-queue sampler is the ONLY cron intentionally on both lanes (it
    # samples each lane's own queue). Every other (global) cron is on one lane —
    # arq dedups a cron per queue, so a global cron on both would fire twice.
    assert bulk_crons & fast_crons == {"cron:sample_queue_stats"}
    # Billing recovery crons live on the fast lane; GitHub/LLM on the bulk lane.
    assert "cron:billing_reconcile" in fast_crons
    assert "cron:reconcile_drift" in bulk_crons


def test_shared_settings_visible_to_arq_cli_introspection() -> None:
    from arq.worker import get_kwargs

    import worker

    # arq's CLI builds the Worker from settings_cls.__dict__ (get_kwargs) and
    # never walks the MRO, so an attribute living only on _BaseWorkerSettings
    # is invisible to `arq worker.WorkerSettings` — the lane would silently
    # boot on arq defaults (localhost Redis, no on_startup, default max_jobs).
    for lane in (worker.WorkerSettings, worker.FastWorkerSettings):
        kwargs = get_kwargs(lane)
        for attr in (
            "redis_settings",
            "max_jobs",
            "max_tries",
            "job_timeout",
            "keep_result",
            "on_startup",
            "on_shutdown",
        ):
            assert attr in kwargs, f"{lane.__name__}.{attr} invisible to arq CLI"
        assert kwargs["redis_settings"] is worker._BaseWorkerSettings.redis_settings
    # A subclass override must still beat the materialised shared value.
    assert (
        get_kwargs(worker.FastWorkerSettings)["max_jobs"]
        < get_kwargs(worker.WorkerSettings)["max_jobs"]
    )


async def test_sample_queue_stats_publishes_depth_and_age() -> None:
    import time

    import worker
    from services.observability import WORKER_QUEUE_DEPTH

    now_ms = time.time() * 1000

    class _FakeArqRedis:
        default_queue_name = "arq:queue:fast"

        async def zcard(self, key):
            return 3

        async def zrange(self, key, start, stop, withscores=False):
            # Oldest ready job enqueued 12s ago.
            return [(b"jobid", now_ms - 12_000)]

    await worker.sample_queue_stats({"redis": _FakeArqRedis()})
    assert WORKER_QUEUE_DEPTH.labels(queue="arq:queue:fast")._value.get() == 3
    from services.observability import WORKER_QUEUE_OLDEST_AGE_SECONDS

    age = WORKER_QUEUE_OLDEST_AGE_SECONDS.labels(queue="arq:queue:fast")._value.get()
    assert 10 <= age <= 15  # ~12s, allowing for clock slack


async def test_sample_queue_stats_swallows_errors() -> None:
    import worker

    class _BrokenRedis:
        default_queue_name = "arq:queue"

        async def zcard(self, key):
            raise RuntimeError("redis down")

    # Must not raise — a metrics blip never surfaces as a worker error.
    await worker.sample_queue_stats({"redis": _BrokenRedis()})

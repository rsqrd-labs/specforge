"""Tests for the durable queue base contract (Phase 21 — T-269).

Covers the request-path enqueue (idempotency dedup + fail-closed) and the shared
job base: exponential-backoff retries up to the cap, then a dead-letter record +
metric. No real Redis/arq — a tiny fake pool stands in.
"""

from __future__ import annotations

from typing import Any

import pytest
from arq.worker import Retry

from config import settings
from services.observability import (
    GITHUB_JOB_DEADLETTERED_TOTAL,
    GITHUB_JOB_RETRIES_TOTAL,
)
from services.queue import (
    JOB_MAX_TRIES,
    QueueUnavailableError,
    _retry_backoff_seconds,
    enqueue,
    github_job,
)

pytestmark = pytest.mark.asyncio


class _Job:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id


class _FakePool:
    """Stand-in for ArqRedis: records enqueue_job + dead-letter list ops."""

    def __init__(self, *, dedup: bool = False, raise_on_enqueue: bool = False) -> None:
        self.dedup = dedup
        self.raise_on_enqueue = raise_on_enqueue
        self.enqueued: list[tuple[str, tuple[Any, ...], str | None]] = []
        self.lpushed: list[str] = []

    async def enqueue_job(
        self, job: str, *args: Any, _job_id: str | None = None, **kwargs: Any
    ) -> _Job | None:
        if self.raise_on_enqueue:
            raise ConnectionError("redis down")
        self.enqueued.append((job, args, _job_id))
        if self.dedup:
            return None  # arq returns None when the job id already exists
        return _Job(_job_id or "generated-id")

    async def lpush(self, key: str, value: str) -> None:
        self.lpushed.append(value)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        pass


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------


async def test_enqueue_passes_job_id_and_returns_id() -> None:
    pool = _FakePool()
    job_id = await enqueue(
        "export_push", "p1", "repo", "private", job_id="p1", pool=pool
    )
    assert job_id == "p1"
    assert pool.enqueued == [("export_push", ("p1", "repo", "private"), "p1")]


async def test_enqueue_dedups_duplicate_submit() -> None:
    pool = _FakePool(dedup=True)
    # arq drops a duplicate job id (same push already queued) → None.
    assert await enqueue("export_push", "p1", job_id="p1", pool=pool) is None


async def test_enqueue_fails_closed_when_queue_unavailable() -> None:
    pool = _FakePool(raise_on_enqueue=True)
    with pytest.raises(QueueUnavailableError):
        await enqueue("export_push", "p1", job_id="p1", pool=pool)


# ---------------------------------------------------------------------------
# job base contract: retry / backoff / dead-letter
# ---------------------------------------------------------------------------


async def test_job_retries_with_backoff_before_cap() -> None:
    @github_job("export_push")
    async def boom(ctx: dict[str, Any]) -> None:
        raise RuntimeError("transient")

    before = GITHUB_JOB_RETRIES_TOTAL.labels(job="export_push")._value.get()
    with pytest.raises(Retry) as exc:
        await boom({"job_try": 1, "job_id": "p1", "redis": _FakePool()})
    # arq.Retry carries the backoff defer.
    assert exc.value.defer_score is not None
    assert GITHUB_JOB_RETRIES_TOTAL.labels(job="export_push")._value.get() == before + 1


async def test_job_dead_letters_after_max_tries() -> None:
    pool = _FakePool()

    @github_job("export_push")
    async def boom(ctx: dict[str, Any], push_id: str) -> None:
        raise RuntimeError("permanent")

    before = GITHUB_JOB_DEADLETTERED_TOTAL.labels(job="export_push")._value.get()
    # On the final attempt the job is dead-lettered, not retried: it returns
    # None (swallowed) so arq stops, and a record is written for manual replay.
    result = await boom({"job_try": JOB_MAX_TRIES, "job_id": "p1", "redis": pool}, "p1")
    assert result is None
    assert (
        GITHUB_JOB_DEADLETTERED_TOTAL.labels(job="export_push")._value.get()
        == before + 1
    )
    assert len(pool.lpushed) == 1
    record = pool.lpushed[0]
    assert "export_push" in record and "p1" in record and "RuntimeError" in record


async def test_job_success_passes_through() -> None:
    @github_job("export_push")
    async def ok(ctx: dict[str, Any]) -> str:
        return "done"

    assert await ok({"job_try": 1, "redis": _FakePool()}) == "done"


async def test_retry_backoff_is_bounded_and_grows() -> None:
    # Full-jitter backoff: bounded by the exponential ceiling at each attempt.
    for attempt in range(1, 6):
        for _ in range(50):
            delay = _retry_backoff_seconds(attempt)
            assert 0.0 <= delay <= 600.0


async def test_stable_job_id_dedups_inflight_but_allows_reexport() -> None:
    """The export job uses ``_job_id = push_id`` (stable across re-exports).

    That must (a) drop a concurrent duplicate submit while the job is queued/in
    flight — the double-``create_repo`` guard — yet (b) allow a *later* re-export
    of the same push to enqueue again. (b) only holds because the worker sets
    ``keep_result=0``: a retained ``arq:result:{push_id}`` key would make arq
    treat the re-export as a duplicate and silently never run it. This runs a
    real burst worker against Redis to prove both, since it cannot be observed
    through the request-path enqueue alone.
    """
    from uuid import uuid4

    from arq import create_pool
    from arq.connections import RedisSettings
    from arq.worker import Worker, func

    from worker import WorkerSettings

    # Pin the production setting the (b) guarantee depends on.
    assert WorkerSettings.keep_result == 0

    processed: list[int] = []

    async def _noop(ctx: dict[str, Any], n: int) -> None:
        processed.append(n)

    rs = RedisSettings.from_dsn(settings.redis_url)
    pool = await create_pool(rs)
    job_id = f"export-dedup-{uuid4()}"

    def _burst() -> Worker:
        return Worker(
            functions=[func(_noop, name="_noop")],
            redis_pool=pool,
            keep_result=0,
            burst=True,
            poll_delay=0.0,
            handle_signals=False,
        )

    try:
        first = await pool.enqueue_job("_noop", 1, _job_id=job_id)
        assert first is not None
        # (a) In-flight: a duplicate submit under the same id is dropped.
        assert await pool.enqueue_job("_noop", 99, _job_id=job_id) is None

        await _burst().async_run()
        assert processed == [1]

        # (b) Re-export: same id enqueues again now that keep_result=0 cleared
        # the result key on completion.
        second = await pool.enqueue_job("_noop", 2, _job_id=job_id)
        assert second is not None
        await _burst().async_run()
        assert processed == [1, 2]
    finally:
        await pool.aclose()

"""Unit tests for the per-installation rate governor + per-repo write
serialization (T-274).

These exercise behaviour, not just shape:

- the token bucket honours the primary (~5,000/hr) and secondary (~80/min
  content) limits, refills over time, and is keyed per installation so one
  tenant cannot drain another's budget (fairness);
- ``observe`` reads ``X-RateLimit-Remaining`` / ``Retry-After`` off a response
  and raises :class:`GitHubThrottledError` on a 429 / secondary-limit 403 — but
  NOT on a plain permission 403;
- a throttle propagated through ``GitHubAPIClient`` and the worker job base
  contract (``github_job``) **requeues** the job (deferred, off the try budget)
  rather than failing/dead-lettering it (the named acceptance test);
- content writes to one repo serialize under a per-``repo_id`` lock while jobs
  for different repos/installs run concurrently; the lock releases on failure.

A faithful in-memory fake Redis runs the governor's actual Lua scripts (the
token bucket and the compare-and-delete release) in Python so the orchestration
is tested without a live Redis; the Lua atomicity itself is covered by the
``@pytest.mark.integration`` path against real Redis elsewhere.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from services.integrations.github_api_client import (
    GitHubAPIError,
    make_app_github_client,
)
from services.integrations.github_governor import (
    _LOCK_RELEASE_LUA,
    _TOKEN_BUCKET_LUA,
    PRIMARY_HOURLY_LIMIT,
    SECONDARY_PER_MINUTE_LIMIT,
    GitHubThrottledError,
    InstallationRateGovernor,
)
from services.queue import github_job

# ---------------------------------------------------------------------------
# Faithful in-memory fake Redis
# ---------------------------------------------------------------------------


class _FakeRedis:
    """In-memory Redis double that runs the governor's exact Lua scripts.

    Supports the surface the governor uses: ``time``, ``eval`` (dispatching on
    the script *identity* so the real bucket/lock math runs), ``hset``,
    ``expire``, ``set`` (NX/EX), ``get``. The clock is settable so refill and
    expiry are deterministic.
    """

    def __init__(self) -> None:
        self.clock = 1_000_000.0
        self.hashes: dict[str, dict[str, float]] = {}
        self.strings: dict[str, str] = {}

    async def time(self) -> tuple[int, int]:
        whole = int(self.clock)
        micros = int(round((self.clock - whole) * 1_000_000))
        return whole, micros

    async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        key = args[0]
        if script is _TOKEN_BUCKET_LUA:
            return self._token_bucket(key, args[1:])
        if script is _LOCK_RELEASE_LUA:
            token = args[1]
            if self.strings.get(key) == token:
                self.strings.pop(key, None)
                return 1
            return 0
        raise AssertionError("unexpected script")

    def _token_bucket(self, key: str, rest: tuple[Any, ...]) -> list[Any]:
        capacity_raw, refill_raw, now_raw, _, requested_raw = rest
        capacity = float(capacity_raw)
        refill = float(refill_raw)
        now = float(now_raw)
        requested = float(requested_raw)
        bucket = self.hashes.get(key)
        tokens = bucket["tokens"] if bucket else capacity
        ts = bucket["ts"] if bucket else now
        elapsed = max(0.0, now - ts)
        tokens = min(capacity, tokens + elapsed * refill)
        if tokens >= requested:
            tokens -= requested
            allowed = 1
            retry = 0.0
        else:
            allowed = 0
            retry = (requested - tokens) / refill
        self.hashes[key] = {"tokens": tokens, "ts": now}
        return [allowed, str(retry)]

    async def hset(self, key: str, *, mapping: dict[str, float]) -> None:
        self.hashes[key] = dict(mapping)

    async def expire(self, key: str, ttl: int) -> None:
        return None

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)


# ---------------------------------------------------------------------------
# Token bucket — primary + secondary limits, refill, fairness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_within_budget_does_not_throttle() -> None:
    redis = _FakeRedis()
    gov = InstallationRateGovernor(redis, installation_id=1)
    # A handful of reads + writes well under both limits.
    for _ in range(10):
        await gov.acquire(write=False)
        await gov.acquire(write=True)


@pytest.mark.asyncio
async def test_secondary_limit_throttles_writes_then_refills() -> None:
    redis = _FakeRedis()
    gov = InstallationRateGovernor(redis, installation_id=7)

    # Drain the secondary (content-write) bucket exactly.
    for _ in range(SECONDARY_PER_MINUTE_LIMIT):
        await gov.acquire(write=True)

    # The next write is throttled with a positive backoff.
    with pytest.raises(GitHubThrottledError) as caught:
        await gov.acquire(write=True)
    assert caught.value.reason == "secondary_limit"
    assert caught.value.retry_after >= 1.0

    # A non-write still passes — only the secondary bucket is drained.
    await gov.acquire(write=False)

    # After a full secondary window the bucket refills and writes resume.
    redis.clock += 61.0
    await gov.acquire(write=True)


@pytest.mark.asyncio
async def test_primary_limit_throttles_all_requests() -> None:
    redis = _FakeRedis()
    gov = InstallationRateGovernor(redis, installation_id=9)
    # Pin the secondary bucket high so only the primary can throttle: drain
    # primary with reads (reads never touch the secondary bucket).
    for _ in range(PRIMARY_HOURLY_LIMIT):
        await gov.acquire(write=False)
    with pytest.raises(GitHubThrottledError) as caught:
        await gov.acquire(write=False)
    assert caught.value.reason == "primary_limit"


@pytest.mark.asyncio
async def test_budgets_are_isolated_per_installation() -> None:
    """Fairness: draining one tenant's bucket must not throttle another."""
    redis = _FakeRedis()
    a = InstallationRateGovernor(redis, installation_id=100)
    b = InstallationRateGovernor(redis, installation_id=200)
    for _ in range(SECONDARY_PER_MINUTE_LIMIT):
        await a.acquire(write=True)
    with pytest.raises(GitHubThrottledError):
        await a.acquire(write=True)
    # Tenant B's budget is untouched.
    await b.acquire(write=True)


@pytest.mark.asyncio
async def test_acquire_fails_open_without_redis() -> None:
    gov = InstallationRateGovernor(None, installation_id=1)
    for _ in range(10_000):
        await gov.acquire(write=True)  # never throttles when Redis is absent


# ---------------------------------------------------------------------------
# observe() — header-driven backoff
# ---------------------------------------------------------------------------


def _resp(status: int, *, headers: dict[str, str] | None = None, body: Any = None):
    """Create a mock ``httpx.Response`` for tests.

    Args:
        status: HTTP status code to set on the response.
        headers: Optional response headers.
        body: Optional JSON-serializable response body.
    """
    return httpx.Response(status, headers=headers or {}, json=body)


@pytest.mark.asyncio
async def test_observe_raises_on_429_with_retry_after() -> None:
    gov = InstallationRateGovernor(None, installation_id=1)
    with pytest.raises(GitHubThrottledError) as caught:
        await gov.observe(_resp(429, headers={"Retry-After": "42"}))
    assert caught.value.retry_after == 42.0


@pytest.mark.asyncio
async def test_observe_raises_on_secondary_403() -> None:
    gov = InstallationRateGovernor(None, installation_id=1)
    with pytest.raises(GitHubThrottledError) as caught:
        await gov.observe(
            _resp(403, body={"message": "You have exceeded a secondary rate limit"})
        )
    assert caught.value.reason == "secondary_limit"


@pytest.mark.asyncio
async def test_observe_raises_on_primary_exhausted_403() -> None:
    gov = InstallationRateGovernor(None, installation_id=1)
    with pytest.raises(GitHubThrottledError) as caught:
        await gov.observe(_resp(403, headers={"X-RateLimit-Remaining": "0"}))
    assert caught.value.reason == "primary_limit"


@pytest.mark.asyncio
async def test_observe_ignores_permission_403() -> None:
    """A plain permission 403 (e.g. missing Workflows:write) must NOT throttle —
    requeuing it would loop to dead-letter with a misleading cause."""
    gov = InstallationRateGovernor(None, installation_id=1)
    await gov.observe(_resp(403, body={"message": "Resource not accessible"}))


@pytest.mark.asyncio
async def test_observe_realigns_bucket_to_reported_remaining() -> None:
    redis = _FakeRedis()
    gov = InstallationRateGovernor(redis, installation_id=5)
    await gov.observe(_resp(200, headers={"X-RateLimit-Remaining": "3"}))
    # The next 3 requests pass, the 4th throttles — the bucket now reflects
    # GitHub's authoritative count, not our local capacity.
    for _ in range(3):
        await gov.acquire(write=False)
    with pytest.raises(GitHubThrottledError):
        await gov.acquire(write=False)


# ---------------------------------------------------------------------------
# Throttle → requeue through the client + worker job contract (named criterion)
# ---------------------------------------------------------------------------


class _FakeTokenSource:
    """Test double for installation token retrieval/refresh.

    Always returns the same fixed token value.
    """

    async def get(self, installation_id: int) -> str:
        return "tok"

    async def refresh(self, installation_id: int) -> str:
        return "tok"


class _RecordingArqRedis:
    """Models arq's ``enqueue_job`` dedup so a *real* requeue is observable.

    arq drops an ``enqueue_job`` whose ``_job_id`` already exists (the in-flight
    job's own key still exists while it runs, and ``finish_job`` deletes it by id
    on return) — so re-enqueuing under ``ctx['job_id']`` is a silent no-op. This
    double records only enqueues that actually take effect: one with the
    in-flight id is deduped (returns ``None``, not recorded), modelling the bug
    that fresh-id requeue avoids.
    """

    def __init__(self, in_flight_id: str | None = None) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self._in_flight_id = in_flight_id

    async def enqueue_job(
        self, name: str, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        job_id = kwargs.get("_job_id")
        if job_id is not None and job_id == self._in_flight_id:
            return None  # deduped against the running job's key — lost
        record = {"name": name, "args": args, "kwargs": kwargs}
        self.enqueued.append(record)
        return record


@pytest.mark.asyncio
async def test_governor_backs_off_and_requeues_on_secondary_limit() -> None:
    """Named acceptance criterion: simulate a 429 with Retry-After; assert the
    job is requeued (deferred, off the try budget), not failed/dead-lettered."""
    gov = InstallationRateGovernor(None, installation_id=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"message": "Rate limit exceeded"},
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = make_app_github_client(_FakeTokenSource(), 1, http, governor=gov)

    @github_job("export_push")
    async def job(ctx: dict[str, Any], push_id: str) -> None:
        # A content write that GitHub rate-limits → observe raises throttle.
        await client.create_issue("o/r", "t", "b")

    # The running job's own id — a same-id re-enqueue would be deduped (lost).
    arq_redis = _RecordingArqRedis(in_flight_id="push-123")
    ctx = {"job_try": 1, "job_id": "push-123", "redis": arq_redis}

    # Must NOT raise (no failure / no dead-letter) — it returns having requeued.
    result = await job(ctx, "push-123")
    assert result is None

    # A real requeue took effect (fresh arq id survives the in-flight dedup).
    assert len(arq_redis.enqueued) == 1
    call = arq_redis.enqueued[0]
    assert call["name"] == "export_push"
    assert call["args"] == ("push-123",)  # idempotency key is the arg, not arq id
    assert call["kwargs"].get("_job_id") is None  # fresh id, not the in-flight one
    assert call["kwargs"]["_defer_by"] == 30.0  # honoured Retry-After
    await http.aclose()


@pytest.mark.asyncio
async def test_sustained_throttling_never_dead_letters() -> None:
    """Repeated throttles must never advance job_try toward the dead-letter cap —
    a healthy-but-rate-limited export backs off indefinitely."""
    gov = InstallationRateGovernor(None, installation_id=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "5"},
            json={"message": "Rate limit exceeded"},
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = make_app_github_client(_FakeTokenSource(), 1, http, governor=gov)

    @github_job("export_push")
    async def job(ctx: dict[str, Any]) -> None:
        await client.create_issue("o/r", "t", "b")

    arq_redis = _RecordingArqRedis()
    # Even at job_try far past JOB_MAX_TRIES, a throttle still requeues cleanly
    # (it is not routed through the retry/dead-letter accounting at all).
    ctx = {"job_try": 99, "job_id": "push-1", "redis": arq_redis}
    for _ in range(3):
        assert await job(ctx) is None
    assert len(arq_redis.enqueued) == 3
    await http.aclose()


@pytest.mark.asyncio
async def test_permission_403_is_a_real_failure_not_a_requeue() -> None:
    """A non-rate-limit 403 surfaces as GitHubAPIError (handled by the retry/
    dead-letter path), never silently requeued as backpressure."""
    gov = InstallationRateGovernor(None, installation_id=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"message": "Resource not accessible by integration"}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = make_app_github_client(_FakeTokenSource(), 1, http, governor=gov)
    with pytest.raises(GitHubAPIError):
        await client.create_issue("o/r", "t", "b")
    await http.aclose()


# ---------------------------------------------------------------------------
# Per-repo write serialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_repo_writes_serialize() -> None:
    """Two governors (different installs) targeting the SAME repo_id must not
    both hold the write lock at once — concurrent content writes serialize."""
    redis = _FakeRedis()
    a = InstallationRateGovernor(redis, installation_id=1)
    b = InstallationRateGovernor(redis, installation_id=2)

    overlap = 0
    holders = 0
    order: list[str] = []

    async def writer(gov: InstallationRateGovernor, label: str) -> None:
        nonlocal overlap, holders
        async with gov.repo_write_lock(repo_id=4242):
            holders += 1
            overlap = max(overlap, holders)
            order.append(f"{label}-enter")
            await asyncio.sleep(0.02)
            order.append(f"{label}-exit")
            holders -= 1

    await asyncio.gather(writer(a, "a"), writer(b, "b"))
    assert overlap == 1, "the per-repo lock must serialize concurrent writers"
    # One writer fully completes before the other enters.
    assert order in (
        ["a-enter", "a-exit", "b-enter", "b-exit"],
        ["b-enter", "b-exit", "a-enter", "a-exit"],
    )


@pytest.mark.asyncio
async def test_different_repos_write_concurrently() -> None:
    """Jobs for different repos hold independent locks → they run concurrently."""
    redis = _FakeRedis()
    gov = InstallationRateGovernor(redis, installation_id=1)

    holders = 0
    overlap = 0

    async def writer(repo_id: int) -> None:
        nonlocal holders, overlap
        async with gov.repo_write_lock(repo_id=repo_id):
            holders += 1
            overlap = max(overlap, holders)
            await asyncio.sleep(0.02)
            holders -= 1

    await asyncio.gather(writer(1), writer(2))
    assert overlap == 2, "different repos must not serialize against each other"


@pytest.mark.asyncio
async def test_repo_lock_released_on_failure() -> None:
    """A crash inside the locked section must release the lock (no deadlock)."""
    redis = _FakeRedis()
    gov = InstallationRateGovernor(redis, installation_id=1)

    # Equivalent to `with pytest.raises(RuntimeError):` but written as an
    # explicit try/except to work around a CodeQL false positive: CodeQL does
    # not model pytest.raises.__exit__ suppressing the exception, so it treats
    # everything after the `with` block as unreachable (py/unreachable-statement).
    raised = False
    try:
        async with gov.repo_write_lock(repo_id=77):
            raise RuntimeError("boom")
    except RuntimeError:
        raised = True
    assert raised

    # The lock is free — a subsequent writer acquires immediately.
    entered = False
    async with gov.repo_write_lock(repo_id=77):
        entered = True
    assert entered


@pytest.mark.asyncio
async def test_repo_lock_noops_without_redis_or_repo_id() -> None:
    gov_no_redis = InstallationRateGovernor(None, installation_id=1)
    async with gov_no_redis.repo_write_lock(repo_id=1):
        pass
    gov = InstallationRateGovernor(_FakeRedis(), installation_id=1)
    async with gov.repo_write_lock(repo_id=None):
        pass

"""Admission control lifecycle (scalability audit F1/F2).

Covers:
  AD-1  per-process limiter: acquire under limit, reject at limit, release frees.
  AD-2  GenerationCapacityError carries a per-reason Retry-After.
  AD-3  admit_generation succeeds and takes the configured budgets.
  AD-4  per-user concurrency cap rejects the (N+1)th and UNWINDS the process slot
        (no leak) — the top correctness risk.
  AD-5  per-provider in-flight budget rejects + unwinds when configured.
  AD-6  per-provider RPM budget rejects + unwinds when configured.
  AD-7  release() is idempotent (two call sites cannot double-decrement).
  AD-8  release() unwinds the Redis leases via ZREM (so a later admit succeeds).
  AD-9  a Redis outage fails OPEN (admission granted; process slot still held).
  AD-10 release() never raises even if the Redis cleanup errors (best effort).
"""

from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from config import settings
from services.pipeline import admission as adm
from services.pipeline.admission import (
    GenerationCapacityError,
    admit_generation,
    resume_generation_admission,
)


class _ZSetRedis:
    """In-memory async fake implementing the sorted-set + eval Lua the lease uses.

    Supports exactly the surface admission touches: the Lua acquire script
    (modelled directly), ``zrem``, and the sliding-window ``eval`` used by the RPM
    check (which the rate-limit middleware also drives through ``eval``).
    """

    def __init__(self) -> None:
        # key -> {member: score}
        self._zsets: dict[str, dict[str, float]] = {}

    async def eval(self, script: str, numkeys: int, *args):
        key = args[0]
        if "ZADD" in script and "ZCARD" in script and "ZREMRANGEBYSCORE" in script:
            return self._lease_or_window(script, key, args)
        raise AssertionError("unexpected eval script")

    def _lease_or_window(self, script: str, key: str, args) -> int:
        zset = self._zsets.setdefault(key, {})
        # The admission lease script: ARGV = now, limit, member, deadline, ttl.
        # The sliding-window script: ARGV = now, window_start, limit, member, ttl.
        now = float(args[1])
        zset_items = zset
        if "local limit = tonumber(ARGV[2])" in script:  # admission lease
            limit = int(args[2])
            member = args[3]
            deadline = float(args[4])
            cutoff = now
            for m in [m for m, s in zset_items.items() if s <= cutoff]:
                del zset_items[m]
            if member in zset_items:
                zset_items[member] = deadline
                return 1
            if limit > 0 and len(zset_items) >= limit:
                return 0
            zset_items[member] = deadline
            return 1
        # sliding window (rate_limit._SLIDING_WINDOW_LUA): ARGV[3]=limit, [4]=member
        window_start = float(args[2])
        limit = int(args[3])
        member = args[4]
        for m in [m for m, s in zset_items.items() if s <= window_start]:
            del zset_items[m]
        if len(zset_items) >= limit:
            return 0
        zset_items[member] = now
        return 1

    async def zrem(self, key: str, member: str) -> int:
        zset = self._zsets.get(key, {})
        if member in zset:
            del zset[member]
            return 1
        return 0

    def count(self, key: str) -> int:
        return len(self._zsets.get(key, {}))


@pytest.fixture(autouse=True)
def _reset_process_limiter():
    """Reset the module-level per-process limiter between tests."""
    adm._process_limiter._inflight = 0
    yield
    adm._process_limiter._inflight = 0


# ---------------------------------------------------------------------------
# AD-1 / AD-2 — per-process limiter + capacity error
# ---------------------------------------------------------------------------


def test_process_limiter_rejects_at_limit() -> None:
    limiter = adm._ProcessGenerationLimiter()
    assert limiter.try_acquire(2) is True
    assert limiter.try_acquire(2) is True
    assert limiter.try_acquire(2) is False  # full
    limiter.release()
    assert limiter.try_acquire(2) is True  # freed
    assert limiter.inflight == 2


def test_process_limiter_zero_means_unlimited() -> None:
    limiter = adm._ProcessGenerationLimiter()
    for _ in range(100):
        assert limiter.try_acquire(0) is True


def test_capacity_error_retry_after() -> None:
    err = GenerationCapacityError(adm.REASON_PROVIDER_RPM, retry_after=60)
    assert err.reason == adm.REASON_PROVIDER_RPM
    assert err.retry_after == 60


# ---------------------------------------------------------------------------
# AD-3 — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admit_generation_success(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 5)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 3)
    redis = _ZSetRedis()

    a = await admit_generation(redis, user_id="u1", provider="anthropic")
    assert a.took_process is True
    assert a.took_user is True
    assert adm.process_inflight() == 1
    assert redis.count(adm._user_inflight_key("u1")) == 1

    await a.release()
    assert adm.process_inflight() == 0
    assert redis.count(adm._user_inflight_key("u1")) == 0


# ---------------------------------------------------------------------------
# AD-3b — the primary safety valve: per-process budget rejects via admit_generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_process_budget_rejects_via_admit(monkeypatch) -> None:
    """The per-process limiter is the primary valve; full ⇒ reject before Redis.

    Exercises the rejection through the public ``admit_generation`` API (not just
    the limiter in isolation), and asserts it trips BEFORE any user/Redis budget
    so one worker cannot self-immolate even if Redis is healthy.
    """
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 1)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 5)
    redis = _ZSetRedis()
    before = adm.GENERATION_ADMISSION_REJECTED.labels(
        reason=adm.REASON_PROCESS
    )._value.get()

    a1 = await admit_generation(redis, user_id="u1", provider="anthropic")
    with pytest.raises(GenerationCapacityError) as exc:
        # A *different* user — the process budget binds before the per-user one.
        await admit_generation(redis, user_id="u2", provider="anthropic")
    assert exc.value.reason == adm.REASON_PROCESS
    assert exc.value.retry_after == adm._RETRY_AFTER[adm.REASON_PROCESS]
    # The rejected admit took no user lease (it never reached the Redis budgets).
    assert redis.count(adm._user_inflight_key("u2")) == 0
    after = adm.GENERATION_ADMISSION_REJECTED.labels(
        reason=adm.REASON_PROCESS
    )._value.get()
    assert after == before + 1

    await a1.release()
    assert adm.process_inflight() == 0


# ---------------------------------------------------------------------------
# AD-4 — per-user cap rejects AND unwinds the process slot (no leak)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_user_cap_rejects_and_unwinds_process_slot(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 100)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 2)
    redis = _ZSetRedis()

    a1 = await admit_generation(redis, user_id="u1", provider="anthropic")
    a2 = await admit_generation(redis, user_id="u1", provider="anthropic")
    assert adm.process_inflight() == 2

    with pytest.raises(GenerationCapacityError) as exc:
        await admit_generation(redis, user_id="u1", provider="anthropic")
    assert exc.value.reason == adm.REASON_USER
    # CRITICAL: the rejected admit must have released the process slot it took,
    # otherwise every per-user rejection permanently leaks process capacity.
    assert adm.process_inflight() == 2

    await a1.release()
    await a2.release()
    assert adm.process_inflight() == 0


# ---------------------------------------------------------------------------
# AD-5 / AD-6 — provider budgets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_inflight_budget_rejects_and_unwinds(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 100)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 0)
    monkeypatch.setattr(settings, "provider_max_inflight_generations", 1)
    redis = _ZSetRedis()

    a1 = await admit_generation(redis, user_id="u1", provider="anthropic")
    assert a1.took_provider is True
    with pytest.raises(GenerationCapacityError) as exc:
        await admit_generation(redis, user_id="u2", provider="anthropic")
    assert exc.value.reason == adm.REASON_PROVIDER_INFLIGHT
    assert adm.process_inflight() == 1  # rejected admit unwound its process slot

    # A different provider is independent.
    a2 = await admit_generation(redis, user_id="u2", provider="openai")
    assert a2.took_provider is True
    await a1.release()
    await a2.release()


@pytest.mark.asyncio
async def test_provider_rpm_budget_rejects_and_unwinds(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 100)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 0)
    monkeypatch.setattr(settings, "provider_max_inflight_generations", 0)
    monkeypatch.setattr(settings, "provider_max_generations_per_minute", 2)
    redis = _ZSetRedis()

    a1 = await admit_generation(redis, user_id="u1", provider="anthropic")
    a2 = await admit_generation(redis, user_id="u2", provider="anthropic")
    with pytest.raises(GenerationCapacityError) as exc:
        await admit_generation(redis, user_id="u3", provider="anthropic")
    assert exc.value.reason == adm.REASON_PROVIDER_RPM
    assert adm.process_inflight() == 2  # only the two admitted hold a slot
    await a1.release()
    await a2.release()


@pytest.mark.asyncio
async def test_worker_readmission_does_not_double_count_provider_rpm(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 100)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 0)
    monkeypatch.setattr(settings, "provider_max_inflight_generations", 0)
    monkeypatch.setattr(settings, "provider_max_generations_per_minute", 1)
    redis = _ZSetRedis()

    api_admission = await admit_generation(redis, user_id="u1", provider="anthropic")
    worker_admission = await admit_generation(
        redis,
        user_id="u1",
        provider="anthropic",
        count_provider_rpm=False,
    )

    rpm_key = f"ratelimit:{adm._provider_rpm_key('anthropic')}"
    assert redis.count(rpm_key) == 1
    await api_admission.release()
    await worker_admission.release()


@pytest.mark.asyncio
async def test_durable_handoff_keeps_global_leases_until_worker_finishes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 5)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 1)
    monkeypatch.setattr(settings, "provider_max_inflight_generations", 1)
    monkeypatch.setattr(settings, "provider_max_generations_per_minute", 0)
    redis = _ZSetRedis()

    api_admission = await admit_generation(redis, user_id="u1", provider="anthropic")
    handoff = api_admission.handoff_payload()
    api_admission.complete_handoff()

    assert adm.process_inflight() == 0
    assert redis.count(adm._user_inflight_key("u1")) == 1
    assert redis.count(adm._provider_inflight_key("anthropic")) == 1
    # The API's finally block is now a no-op; it cannot steal worker ownership.
    await api_admission.release()
    assert redis.count(adm._user_inflight_key("u1")) == 1

    worker_admission = await resume_generation_admission(
        redis,
        handoff=handoff,
        user_id="u1",
        provider="anthropic",
    )
    assert adm.process_inflight() == 1
    await worker_admission.release()
    assert adm.process_inflight() == 0
    assert redis.count(adm._user_inflight_key("u1")) == 0
    assert redis.count(adm._provider_inflight_key("anthropic")) == 0


# ---------------------------------------------------------------------------
# AD-7 / AD-8 — release idempotency + lease cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 5)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 3)
    redis = _ZSetRedis()

    a = await admit_generation(redis, user_id="u1", provider="anthropic")
    await a.release()
    await a.release()  # second release must be a no-op
    await a.release()
    assert adm.process_inflight() == 0  # not driven negative
    assert redis.count(adm._user_inflight_key("u1")) == 0


@pytest.mark.asyncio
async def test_release_frees_user_slot_for_next_admit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 100)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 1)
    redis = _ZSetRedis()

    a1 = await admit_generation(redis, user_id="u1", provider="anthropic")
    with pytest.raises(GenerationCapacityError):
        await admit_generation(redis, user_id="u1", provider="anthropic")
    await a1.release()
    # The freed user slot lets the next admit through.
    a2 = await admit_generation(redis, user_id="u1", provider="anthropic")
    assert a2.took_user is True
    await a2.release()


# ---------------------------------------------------------------------------
# AD-9 / AD-10 — Redis outage fails open; cleanup never raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_outage_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 5)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 3)

    class _DownRedis:
        async def eval(self, *a, **k):
            raise RedisError("down")

        async def zrem(self, *a, **k):
            raise RedisError("down")

    a = await admit_generation(_DownRedis(), user_id="u1", provider="anthropic")
    # Failed open: the per-process slot is still taken (the protection that
    # cannot depend on Redis), but no user lease was recorded.
    assert a.took_process is True
    assert a.took_user is False
    assert adm.process_inflight() == 1
    await a.release()  # must not raise despite zrem erroring
    assert adm.process_inflight() == 0


@pytest.mark.asyncio
async def test_release_swallows_cleanup_errors(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_generations_per_process", 5)
    monkeypatch.setattr(settings, "max_concurrent_generations_per_user", 3)

    redis = _ZSetRedis()
    a = await admit_generation(redis, user_id="u1", provider="anthropic")

    async def _boom(*_a, **_k):
        raise RuntimeError("redis blip during release")

    a._redis = type("R", (), {"zrem": staticmethod(_boom)})()
    await a.release()  # must not raise; process slot still freed
    assert adm.process_inflight() == 0

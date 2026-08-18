"""Admission control for the stage-generation path (scalability audit F1/F2).

Nothing on the generation path caps how many generations run at once. Unbounded
concurrent generations saturate the event loop, fan out unbounded background work,
and pile onto the single shared platform LLM key — which hits its account rate
ceiling (429s) long before CPU or DB limits. This module is the admission valve:
before any provider call, a generation must acquire a slot across three budgets,
and is fast-failed (a retryable "busy" signal carrying Retry-After) when over.

Budgets, in acquire order (cheapest/most-local first):

1. **Per-process** (``max_concurrent_generations_per_process``) — an in-memory,
   non-blocking counter. The primary safety valve so one worker process cannot
   self-immolate. Sized off the measured provider budget.
2. **Per-user concurrency** (``max_concurrent_generations_per_user``) — a
   self-healing Redis lease (sorted set of in-flight ids scored by expiry), so it
   holds across processes/instances and recovers if a process dies.
3. **Per-provider budget** (F2) — a global Redis concurrency lease + RPM sliding
   window against the shared key, so the system sheds on *our* budget before the
   provider returns a 429. Concurrency ships conservatively bounded; RPM remains
   unlimited until the real per-org limit is measured (audit §F2/§6).

The lease tracks exactly which budgets it took so a rejection at a later budget
unwinds the earlier acquisitions (no slot leak), and ``release()`` is idempotent
because two call sites may fire it (the pipeline teardown on the handed-off path,
and the generator on a preflight failure). Redis budgets fail **open** on a Redis
outage — a generation is never blocked by a Redis blip — while the in-memory
per-process limiter still applies.
"""

from __future__ import annotations

import logging
import time
import uuid

from prometheus_client import Counter, Gauge
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config import settings
from middleware.rate_limit import sliding_window_check

logger = logging.getLogger(__name__)

# Rejection reasons (bounded enum — Prometheus label).
REASON_PROCESS = "process"
REASON_USER = "user"
REASON_PROVIDER_INFLIGHT = "provider_inflight"
REASON_PROVIDER_RPM = "provider_rpm"

# Retry-After (seconds) advertised per reason. Concurrency budgets free up in
# seconds–tens of seconds as in-flight generations finish; the RPM window is a
# fixed minute, so its hint is the window length.
_RETRY_AFTER = {
    REASON_PROCESS: 5,
    REASON_USER: 10,
    REASON_PROVIDER_INFLIGHT: 10,
    REASON_PROVIDER_RPM: 60,
}

GENERATION_ADMISSION_REJECTED = Counter(
    "thought2build_generation_admission_rejected_total",
    "Stage generations rejected by admission control before any provider call, "
    "by the budget that tripped (process / user / provider_inflight / provider_rpm).",
    ["reason"],
)
GENERATION_INFLIGHT_PROCESS = Gauge(
    "thought2build_generation_inflight_process",
    "In-flight stage generations admitted on this worker process (per-process "
    "admission counter). A persistent non-zero floor at idle indicates a slot leak.",
)

# Atomic concurrency lease: evict expired leases, count active, reject if at the
# limit, else add this member scored by its expiry deadline. A single Lua call so
# two concurrent admissions can never both read "under limit" and both add.
# KEYS[1]=zset; ARGV: now_ms, limit, member, deadline_ms, ttl_seconds.
_LEASE_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
local deadline = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZSCORE', key, member) then
  redis.call('ZADD', key, deadline, member)
  redis.call('EXPIRE', key, ttl)
  return 1
end
local count = redis.call('ZCARD', key)
if limit > 0 and count >= limit then
  return 0
end
redis.call('ZADD', key, deadline, member)
redis.call('EXPIRE', key, ttl)
return 1
"""


def _user_inflight_key(user_id: str) -> str:
    return f"gen:inflight:user:{user_id}"


def _provider_inflight_key(provider: str) -> str:
    return f"gen:inflight:provider:{provider}"


def _provider_rpm_key(provider: str) -> str:
    return f"gen:rpm:provider:{provider}"


class GenerationCapacityError(Exception):
    """Admission rejected because a budget is at capacity (carries Retry-After)."""

    def __init__(self, reason: str, retry_after: int) -> None:
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(f"generation admission rejected ({reason})")


class _ProcessGenerationLimiter:
    """A non-blocking, fast-fail per-process concurrency counter.

    Deliberately not an ``asyncio.Semaphore``: admission must *reject* over-budget
    work, not queue it, and the gauge needs the live count. With one event loop
    per process the check-then-increment in ``try_acquire`` is atomic — there is
    no ``await`` between the comparison and the increment, so the loop cannot
    interleave another coroutine in the gap.
    """

    def __init__(self) -> None:
        self._inflight = 0

    @property
    def inflight(self) -> int:
        return self._inflight

    def try_acquire(self, limit: int) -> bool:
        if limit > 0 and self._inflight >= limit:
            return False
        self._inflight += 1
        GENERATION_INFLIGHT_PROCESS.set(self._inflight)
        return True

    def release(self) -> None:
        if self._inflight > 0:
            self._inflight -= 1
            GENERATION_INFLIGHT_PROCESS.set(self._inflight)


# Module-level singleton: the per-process limiter is process-wide state.
_process_limiter = _ProcessGenerationLimiter()


def process_inflight() -> int:
    """Current per-process in-flight count (for tests/diagnostics)."""
    return _process_limiter.inflight


class GenerationAdmission:
    """A held admission slot. Release exactly once when the generation terminates.

    Records which budgets it actually took so ``release()`` only undoes those, and
    is idempotent so the two release sites (pipeline teardown / preflight failure)
    cannot double-release. The Redis cleanup is best-effort — the leases also
    self-expire via their score, so a dropped ZREM self-heals.
    """

    def __init__(self, redis: Redis, *, user_id: str, provider: str, member: str):
        self._redis = redis
        self._user_id = user_id
        self._provider = provider
        self._member = member
        self.took_process = False
        self.took_user = False
        self.took_provider = False
        self._released = False

    def handoff_payload(self) -> dict[str, str | bool]:
        """Return the bounded Redis-lease identity stored on a durable job."""
        if self._released:
            raise RuntimeError("cannot hand off a released generation admission")
        return {
            "member": self._member,
            "user_id": self._user_id,
            "provider": self._provider,
            "took_user": self.took_user,
            "took_provider": self.took_provider,
        }

    def complete_handoff(self) -> None:
        """Transfer Redis leases to the queued job and release API-local state."""
        if self._released:
            return
        if self.took_process:
            _process_limiter.release()
            self.took_process = False
        # The worker reconstructs ownership from handoff_payload(). The API must
        # no longer ZREM those shared leases in its surrounding finally block.
        self._released = True

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.took_process:
            _process_limiter.release()
        keys: list[str] = []
        if self.took_user:
            keys.append(_user_inflight_key(self._user_id))
        if self.took_provider:
            keys.append(_provider_inflight_key(self._provider))
        if not keys:
            return
        try:
            for key in keys:
                await self._redis.zrem(key, self._member)
        except Exception:
            # Best-effort cleanup: the lease score self-expires, so a failed ZREM
            # self-heals. Releasing the slot early must never crash a generation
            # that has already terminated, so any error here is swallowed (the
            # in-memory per-process counter was already released above).
            logger.warning("admission.release_redis_failed", exc_info=True)


def _reject(reason: str) -> GenerationCapacityError:
    GENERATION_ADMISSION_REJECTED.labels(reason=reason).inc()
    return GenerationCapacityError(reason, retry_after=_RETRY_AFTER[reason])


async def admit_generation(
    redis: Redis,
    *,
    user_id: str,
    provider: str,
    count_provider_rpm: bool = True,
) -> GenerationAdmission:
    """Acquire a generation slot across all configured budgets, or reject (F1/F2).

    Raises ``GenerationCapacityError`` (carrying a Retry-After) when any budget is
    full, unwinding budgets already taken so no slot leaks. Redis budgets fail
    **open** on a Redis outage; the per-process limiter still applies. The caller
    owns the returned admission and must ``release()`` it exactly once when the
    generation terminates. A durable worker re-admits the already-counted API
    request with ``count_provider_rpm=False`` so one generation consumes one RPM
    slot, not one slot at enqueue and a second when its job starts.
    """
    # The per-process and per-user/provider leases use a shared member id so a
    # single ZREM per key cleans up on release.
    member = uuid.uuid4().hex
    admission = GenerationAdmission(
        redis, user_id=user_id, provider=provider, member=member
    )

    # 1. Per-process (in-memory, non-blocking). Always enforced first/cheapest.
    if not _process_limiter.try_acquire(
        settings.max_concurrent_generations_per_process
    ):
        raise _reject(REASON_PROCESS)
    admission.took_process = True

    # 2–4. Redis-coordinated budgets. Fail OPEN on a Redis outage (matching the
    # rate-limit middleware): a generation must not be blocked by a Redis blip.
    try:
        user_limit = settings.max_concurrent_generations_per_user
        if user_limit > 0:
            ok = await _acquire_lease_with_member(
                redis, _user_inflight_key(user_id), user_limit, member
            )
            if not ok:
                await admission.release()
                raise _reject(REASON_USER)
            admission.took_user = True

        provider_inflight_limit = settings.provider_max_inflight_generations
        if provider_inflight_limit > 0:
            ok = await _acquire_lease_with_member(
                redis,
                _provider_inflight_key(provider),
                provider_inflight_limit,
                member,
            )
            if not ok:
                await admission.release()
                raise _reject(REASON_PROVIDER_INFLIGHT)
            admission.took_provider = True

        provider_rpm = settings.provider_max_generations_per_minute
        if count_provider_rpm and provider_rpm > 0:
            allowed = await sliding_window_check(
                redis, _provider_rpm_key(provider), provider_rpm, 60
            )
            if not allowed:
                await admission.release()
                raise _reject(REASON_PROVIDER_RPM)
    except RedisError:
        # Redis unavailable — fail open (the per-process limiter, already taken,
        # remains the protection). Log so operators see the degraded state.
        logger.warning("admission.redis_unavailable_fail_open", exc_info=True)

    return admission


def _admission_from_handoff(
    redis: Redis,
    handoff: dict,
    *,
    user_id: str,
    provider: str,
) -> GenerationAdmission:
    """Validate and reconstruct a durable admission without taking new slots."""
    if not isinstance(handoff, dict):
        raise ValueError("generation admission handoff is missing")
    member = handoff.get("member")
    if not isinstance(member, str) or len(member) != 32:
        raise ValueError("generation admission handoff member is invalid")
    try:
        if uuid.UUID(hex=member).hex != member:
            raise ValueError
    except ValueError as exc:
        raise ValueError("generation admission handoff member is invalid") from exc
    if handoff.get("user_id") != user_id or handoff.get("provider") != provider:
        raise ValueError("generation admission handoff scope does not match run")
    took_user = handoff.get("took_user")
    took_provider = handoff.get("took_provider")
    if not isinstance(took_user, bool) or not isinstance(took_provider, bool):
        raise ValueError("generation admission handoff flags are invalid")
    admission = GenerationAdmission(
        redis,
        user_id=user_id,
        provider=provider,
        member=member,
    )
    admission.took_user = took_user
    admission.took_provider = took_provider
    return admission


async def resume_generation_admission(
    redis: Redis,
    *,
    handoff: dict,
    user_id: str,
    provider: str,
) -> GenerationAdmission:
    """Reacquire worker-local capacity and refresh transferred Redis leases."""
    admission = _admission_from_handoff(
        redis,
        handoff,
        user_id=user_id,
        provider=provider,
    )
    if not _process_limiter.try_acquire(
        settings.max_concurrent_generations_per_process
    ):
        # Preserve the transferred Redis reservation while arq waits to retry.
        raise _reject(REASON_PROCESS)
    admission.took_process = True

    try:
        user_limit = settings.max_concurrent_generations_per_user
        if admission.took_user and user_limit > 0:
            if not await _acquire_lease_with_member(
                redis,
                _user_inflight_key(user_id),
                user_limit,
                admission._member,
            ):
                await admission.release()
                raise _reject(REASON_USER)

        provider_limit = settings.provider_max_inflight_generations
        if admission.took_provider and provider_limit > 0:
            if not await _acquire_lease_with_member(
                redis,
                _provider_inflight_key(provider),
                provider_limit,
                admission._member,
            ):
                await admission.release()
                raise _reject(REASON_PROVIDER_INFLIGHT)
    except RedisError:
        logger.warning("admission.resume_redis_unavailable_fail_open", exc_info=True)
    return admission


async def release_generation_admission_handoff(
    redis: Redis,
    *,
    handoff: dict,
    user_id: str,
    provider: str,
) -> None:
    """Best-effort cleanup when a queued job is already terminal on delivery."""
    admission = _admission_from_handoff(
        redis,
        handoff,
        user_id=user_id,
        provider=provider,
    )
    await admission.release()


async def _acquire_lease_with_member(
    redis: Redis, key: str, limit: int, member: str
) -> bool:
    """Take one concurrency lease in *key* using the admission's shared *member*.

    Using the admission-wide member id (not a fresh per-key one) means a single
    ``ZREM key member`` on release cleans every key the admission added.
    """
    now_ms = int(time.time() * 1000)
    # Never let a live durable run outlast its admission reservation. The
    # configured TTL remains an operator floor; deadline + two minutes bounds
    # stale capacity after an API/worker outage while covering terminal cleanup.
    ttl_seconds = max(
        1,
        settings.generation_admission_lease_ttl_seconds,
        settings.stage_generation_deadline_seconds + 120,
    )
    deadline_ms = now_ms + ttl_seconds * 1000
    result = await redis.eval(
        _LEASE_ACQUIRE_LUA,
        1,
        key,
        str(now_ms),
        str(limit),
        member,
        str(deadline_ms),
        str(ttl_seconds),
    )
    return bool(result)

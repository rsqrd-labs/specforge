"""Per-installation rate governor + per-repo write serialization (Phase 21 — T-274).

A global, multi-tenant SpecForge fleet writes to GitHub on behalf of many
installations at once. Two failure modes have to be engineered out:

1. **Rate-limit exhaustion.** GitHub enforces a *primary* limit (~5,000
   requests/hour per installation) and a *secondary* limit (~80 content-creating
   writes/minute). Blowing either gets the whole installation throttled with
   403/429 — and a naive client retries straight into the wall.
2. **Stale-SHA 409s.** Two jobs writing the same file in the same repo race on
   the blob SHA; the loser gets a 409 and (worse) trips GitHub's secondary
   abuse-detection for hammering one repo.

This module is the *worker-side* enforcement (never request middleware — the
request path returns 202 and the worker does the GitHub I/O). It provides:

- :class:`InstallationRateGovernor` — a Redis-backed **token bucket keyed by
  ``installation_id``** honouring the primary + secondary limits, so one tenant
  cannot monopolise the shared GitHub budget (per-tenant fairness). ``acquire``
  reserves budget *before* a call; ``observe`` reads
  ``X-RateLimit-Remaining`` / ``Retry-After`` off *every* response and, on a
  403 (secondary/primary rate-limit) or 429, raises
  :class:`GitHubThrottledError` so the job is **requeued, not failed**.
- A **per-``repo_id`` Redis lock** (:meth:`InstallationRateGovernor.repo_write_lock`)
  that serializes content writes to a single repository, eliminating stale-SHA
  409s and secondary-limit throttling from concurrent writers.

Reliability invariants:

- **Fail-open on Redis trouble.** A degraded Redis must never brick GitHub work.
  The token bucket and the repo lock both proceed (logged) when Redis errors —
  GitHub's own headers remain the authoritative backstop, and the export
  driver's checkpointing tolerates an occasional 409.
- **Locks release on failure.** The repo lock is context-managed and released
  via a compare-and-delete (token-guarded), so a crashing job can never deadlock
  a repo, and a job can never delete a *different* holder's lock.
- **Backpressure is observable** via ``specforge_github_queue_depth`` (set by the
  worker on each job start) — operators shed/defer when the queue saturates.

The throttle→requeue conversion itself lives in the worker job base contract
(``services.queue.github_job``): a :class:`GitHubThrottledError` is requeued with
a deferred re-enqueue that does **not** consume the dead-letter try budget, so
sustained throttling never dead-letters a healthy job.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import structlog
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

# GitHub published limits (spec §12 / §1725). Kept slightly conservative as a
# *local* backstop — GitHub's response headers are authoritative and ``observe``
# realigns the bucket to the server's reported remaining on every response.
PRIMARY_HOURLY_LIMIT = 5_000
SECONDARY_PER_MINUTE_LIMIT = 80

_PRIMARY_WINDOW_SECONDS = 3_600.0
_SECONDARY_WINDOW_SECONDS = 60.0

# Token-bucket Redis keys are namespaced per installation so one tenant's budget
# is isolated from another's (per-tenant fairness / bulkhead).
_PRIMARY_KEY = "gh:gov:primary:{installation_id}"
_SECONDARY_KEY = "gh:gov:secondary:{installation_id}"
# A bucket key lives at most two windows so an idle installation's keys expire.
_PRIMARY_TTL = int(_PRIMARY_WINDOW_SECONDS * 2)
_SECONDARY_TTL = int(_SECONDARY_WINDOW_SECONDS * 2)

# Per-repo content-write lock.
_REPO_LOCK_KEY = "gh:gov:repolock:{repo_id}"
# The lock TTL must outlast a full content-write phase (the worker job_timeout is
# 1800s) so it cannot expire mid-export and admit a second writer — the exact
# 409 it exists to prevent. It is refreshed on acquisition and released on exit;
# the TTL is only the crash-safety ceiling.
_REPO_LOCK_TTL_SECONDS = 1_800
# Bounded blocking acquire: poll a contended lock for up to this long before
# giving up and requeuing the job (so the other writer finishes first).
_REPO_LOCK_WAIT_SECONDS = 30.0
_REPO_LOCK_POLL_SECONDS = 0.25

# Lua token bucket: atomic refill-then-take so concurrent workers across
# processes see a single consistent budget. Returns {allowed, retry_after_str}.
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local requested = tonumber(ARGV[5])

local bucket = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts = tonumber(bucket[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then
  elapsed = 0
end
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)

local allowed = 0
local retry_after = 0.0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  retry_after = (requested - tokens) / refill_per_sec
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)
return {allowed, tostring(retry_after)}
"""  # nosec B105 — a Lua script literal, not a credential

# Lua compare-and-delete: only release the lock if *we* still hold it (token
# match), so an expired-then-reacquired lock is never dropped by the prior owner.
_LOCK_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class GitHubThrottledError(Exception):
    """Backpressure signal: the job should be **requeued (deferred), not failed**.

    Raised by the governor when budget is exhausted (``acquire``) or when GitHub
    returns a rate-limit 403/429 (``observe``). The worker job base contract
    (``services.queue.github_job``) catches this and re-enqueues the job after
    ``retry_after`` seconds *without* consuming the dead-letter try budget, so a
    rate-limited-but-healthy job is never dead-lettered.

    This is distinct from ``GitHubRateLimitError`` (a terminal typed error on the
    legacy request path) and from ``GitHubUnavailableError`` (circuit-breaker
    open, a GitHub outage). A throttle is expected, transient backpressure.
    """

    def __init__(self, retry_after: float, *, reason: str) -> None:
        super().__init__(f"GitHub throttled ({reason}); retry after {retry_after:.1f}s")
        # Always defer at least a second so a tight retry loop cannot spin.
        self.retry_after = max(1.0, float(retry_after))
        self.reason = reason


class InstallationRateGovernor:
    """Token-bucket rate governor + per-repo write serializer for one install.

    One governor is built per worker job (see :func:`make_governor`) and passed to
    the ``GitHubAPIClient``; it consults Redis so the budget is shared across
    every worker process handling the same ``installation_id``.
    """

    def __init__(
        self,
        redis: "Redis | None",
        installation_id: int,
        *,
        primary_limit: int = PRIMARY_HOURLY_LIMIT,
        secondary_limit: int = SECONDARY_PER_MINUTE_LIMIT,
    ) -> None:
        self._redis = redis
        self._installation_id = installation_id
        self._primary_limit = primary_limit
        self._secondary_limit = secondary_limit
        self._primary_key = _PRIMARY_KEY.format(installation_id=installation_id)
        self._secondary_key = _SECONDARY_KEY.format(installation_id=installation_id)

    # ----- budget reservation -----

    async def acquire(self, *, write: bool) -> None:
        """Reserve budget before a GitHub call; raise on exhaustion.

        Every request consumes a *primary* token. A content-creating ``write``
        (POST/PUT/PATCH/DELETE) also consumes a *secondary* token. The tighter
        secondary budget is checked first so a denied write does not waste a
        primary token. Raises :class:`GitHubThrottledError` (→ requeue) when a
        budget is exhausted. Fail-open on Redis errors.
        """
        if self._redis is None:
            return
        if write:
            await self._take(
                self._secondary_key,
                capacity=self._secondary_limit,
                window=_SECONDARY_WINDOW_SECONDS,
                ttl=_SECONDARY_TTL,
                reason="secondary_limit",
            )
        await self._take(
            self._primary_key,
            capacity=self._primary_limit,
            window=_PRIMARY_WINDOW_SECONDS,
            ttl=_PRIMARY_TTL,
            reason="primary_limit",
        )

    async def _take(
        self,
        key: str,
        *,
        capacity: int,
        window: float,
        ttl: int,
        reason: str,
    ) -> None:
        assert self._redis is not None  # nosec B101 — guarded by acquire()
        refill_per_sec = capacity / window
        try:
            now = await self._now()
            allowed, retry_after = await self._eval_bucket(
                key, capacity, refill_per_sec, now, ttl
            )
        except RedisError:
            # Fail-open: GitHub's own headers (observe) remain the backstop.
            logger.warning("github.governor.bucket_unavailable", key=key)
            return
        if not allowed:
            logger.info(
                "github.governor.throttled",
                installation_id=self._installation_id,
                reason=reason,
                retry_after=retry_after,
            )
            raise GitHubThrottledError(retry_after, reason=reason)

    async def _eval_bucket(
        self,
        key: str,
        capacity: int,
        refill_per_sec: float,
        now: float,
        ttl: int,
    ) -> tuple[bool, float]:
        assert self._redis is not None  # nosec B101
        result = await self._redis.eval(  # type: ignore[no-untyped-call]
            _TOKEN_BUCKET_LUA,
            1,
            key,
            capacity,
            refill_per_sec,
            now,
            ttl,
            1,  # requested tokens
        )
        allowed = bool(int(result[0]))
        retry_after = float(result[1])
        return allowed, retry_after

    # ----- response observation (header-driven backoff) -----

    async def observe(self, response: httpx.Response) -> None:
        """Read GitHub's rate-limit headers off a response; requeue on throttle.

        On a 429 or a rate-limit 403 (secondary abuse-detection or primary
        exhaustion) this raises :class:`GitHubThrottledError` honouring
        ``Retry-After`` so the job backs off and **requeues** rather than failing.
        On a healthy response it realigns the local primary bucket to GitHub's
        authoritative ``X-RateLimit-Remaining`` so our budget tracks reality.
        Fail-open on Redis errors.
        """
        status = response.status_code
        if status == 429 or (status == 403 and _is_rate_limited(response)):
            retry_after = _retry_after_seconds(response)
            reason = "secondary_limit" if _is_secondary(response) else "primary_limit"
            await self._drain(reason)
            logger.info(
                "github.governor.rate_limited",
                installation_id=self._installation_id,
                status=status,
                reason=reason,
                retry_after=retry_after,
            )
            raise GitHubThrottledError(retry_after, reason=reason)

        # Healthy response — realign the primary bucket to the server's count so
        # we slow down *before* hitting the wall on the next request.
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None and remaining.isdigit():
            await self._set_remaining(int(remaining))

    async def _set_remaining(self, remaining: int) -> None:
        if self._redis is None:
            return
        try:
            now = await self._now()
            await self._redis.hset(  # type: ignore[no-untyped-call]
                self._primary_key,
                mapping={"tokens": float(remaining), "ts": now},
            )
            await self._redis.expire(self._primary_key, _PRIMARY_TTL)
        except RedisError:
            logger.debug("github.governor.remaining_sync_failed")

    async def _drain(self, reason: str) -> None:
        """Empty the relevant bucket so concurrent jobs also back off."""
        if self._redis is None:
            return
        key = self._secondary_key if reason == "secondary_limit" else self._primary_key
        try:
            now = await self._now()
            await self._redis.hset(  # type: ignore[no-untyped-call]
                key, mapping={"tokens": 0.0, "ts": now}
            )
            ttl = _SECONDARY_TTL if reason == "secondary_limit" else _PRIMARY_TTL
            await self._redis.expire(key, ttl)
        except RedisError:
            logger.debug("github.governor.drain_failed", reason=reason)

    async def _now(self) -> float:
        """Authoritative time from Redis so all workers share one clock."""
        assert self._redis is not None  # nosec B101
        seconds, micros = await self._redis.time()  # type: ignore[no-untyped-call]
        return float(seconds) + float(micros) / 1_000_000.0

    # ----- per-repo write serialization -----

    @asynccontextmanager
    async def repo_write_lock(self, repo_id: int | str | None) -> AsyncIterator[None]:
        """Serialize content writes to one repo (per-``repo_id`` Redis lock).

        Concurrent content writes to a single repository race on the blob SHA
        (409) and trip GitHub's secondary abuse-detection. Holding this lock for
        the write phase makes those writes sequential. Acquisition blocks (bounded
        poll) up to ``_REPO_LOCK_WAIT_SECONDS``; if the lock stays contended the
        job is requeued (:class:`GitHubThrottledError`) so the other writer
        finishes first. The lock is always released on exit — even on failure —
        via a token-guarded compare-and-delete, so a crash cannot deadlock a repo
        nor drop another holder's lock. Fail-open: no Redis (or ``repo_id`` not
        yet known) means no serialization (the export checkpointing tolerates a
        rare 409).
        """
        if self._redis is None or repo_id is None:
            yield
            return

        key = _REPO_LOCK_KEY.format(repo_id=repo_id)
        token = secrets.token_hex(16)
        acquired = await self._acquire_repo_lock(key, token)
        try:
            yield
        finally:
            if acquired:
                await self._release_repo_lock(key, token)

    async def _acquire_repo_lock(self, key: str, token: str) -> bool:
        assert self._redis is not None  # nosec B101
        deadline_polls = int(_REPO_LOCK_WAIT_SECONDS / _REPO_LOCK_POLL_SECONDS)
        for _ in range(max(1, deadline_polls)):
            try:
                won = await self._redis.set(
                    key, token, nx=True, ex=_REPO_LOCK_TTL_SECONDS
                )
            except RedisError:
                # Fail-open: proceed without the lock (checkpointing tolerates a
                # rare 409). Never block GitHub work on a degraded Redis.
                logger.warning("github.governor.repo_lock_unavailable", repo_key=key)
                return False
            if won:
                return True
            await asyncio.sleep(_REPO_LOCK_POLL_SECONDS)

        # Still contended after the bounded wait — requeue so the holder finishes.
        logger.info("github.governor.repo_lock_contended", repo_key=key)
        raise GitHubThrottledError(_REPO_LOCK_WAIT_SECONDS, reason="repo_contended")

    async def _release_repo_lock(self, key: str, token: str) -> None:
        assert self._redis is not None  # nosec B101
        try:
            await self._redis.eval(_LOCK_RELEASE_LUA, 1, key, token)  # type: ignore[no-untyped-call]
        except RedisError:
            # The TTL guarantees eventual release; a failed delete is non-fatal.
            logger.warning("github.governor.repo_lock_release_failed", repo_key=key)


def make_governor(
    installation_id: int, redis: "Redis | None" = None
) -> InstallationRateGovernor:
    """Build the per-installation governor for a worker job.

    Resolves the shared Redis client when not injected. Tests pass a fake Redis
    (or ``None`` for the fail-open no-Redis path).
    """
    if redis is None:
        from database import get_shared_redis

        redis = get_shared_redis()
    return InstallationRateGovernor(redis, installation_id)


# ---------------------------------------------------------------------------
# Header parsing helpers
# ---------------------------------------------------------------------------


def _is_rate_limited(response: httpx.Response) -> bool:
    """True if a 403 is a rate-limit (primary exhaustion or secondary abuse).

    A plain permission-denied 403 (e.g. missing ``Workflows:write``, T-276) must
    NOT be treated as a throttle — requeuing it would loop to dead-letter with a
    misleading cause. Distinguished by an exhausted remaining count, a
    ``Retry-After`` header, or a rate-limit message in the body.
    """
    if response.headers.get("x-ratelimit-remaining") == "0":
        return True
    if response.headers.get("retry-after") is not None:
        return True
    return _is_secondary(response)


def _is_secondary(response: httpx.Response) -> bool:
    """True if the body signals GitHub's secondary (abuse/content) rate limit."""
    try:
        body = response.json()
    except (ValueError, httpx.DecodingError):
        return False
    if not isinstance(body, dict):
        return False
    message = (body.get("message") or "").lower()
    return "secondary rate" in message or "abuse" in message


def _retry_after_seconds(response: httpx.Response) -> float:
    """Best-effort backoff from ``Retry-After`` or ``X-RateLimit-Reset``.

    Falls back to one secondary window so a throttle without headers still backs
    off meaningfully rather than retrying immediately.
    """
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            # Malformed Retry-After header — ignore it and try x-ratelimit-reset.
            pass
    reset = response.headers.get("x-ratelimit-reset")
    if reset is not None:
        try:
            import time

            delta = float(reset) - time.time()
            if delta > 0:
                return min(delta, _PRIMARY_WINDOW_SECONDS)
        except ValueError:
            # Malformed x-ratelimit-reset header — fall back to the default
            # secondary backoff window below.
            pass
    return _SECONDARY_WINDOW_SECONDS

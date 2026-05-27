import itertools
import logging
import re
import time
from collections.abc import Awaitable, Callable
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from fastapi import status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings
from services.auth_service import decode_access_token_claims

logger = logging.getLogger(__name__)

_LOGIN_PATHS = frozenset({"/auth/google", "/auth/callback"})
_BYPASS_PATHS = frozenset({"/health"})
_LOCAL_FALLBACK_MAX_KEYS = 10_000
# Evict this many oldest entries when the cap is exceeded.  Single-item
# eviction cannot keep up with a burst of distinct IPs; bulk removal bounds
# memory usage while amortising eviction overhead.  M-2 — T-184.
_LOCAL_FALLBACK_EVICT_BATCH = 2_000
_LOGIN_BURST_LIMIT = 5
_LOGIN_BURST_WINDOW_SECONDS = 300
_LOGIN_HOURLY_LIMIT = 20
_LOGIN_HOURLY_WINDOW_SECONDS = 3600

# GitHub export tier (Phase 13): 3 exports per user per hour. Applies to
# POST /workspaces/{id}/export/github only — the ZIP export at
# /workspaces/{id}/export is NOT covered by this tier.
_GITHUB_EXPORT_PATH_RE = re.compile(r"^/workspaces/[^/]+/export/github/?$")
_GITHUB_EXPORT_LIMIT = 3
_GITHUB_EXPORT_WINDOW_SECONDS = 3600
_GITHUB_EXPORT_DETAIL = "GitHub export rate limit reached. Maximum 3 exports per hour."

# Spec Clarification tier (Phase 14): 6 judge-model calls per user per
# hour. Applies to POST /workspaces/{id}/clarify only. The PATCH endpoint
# (which persists answers without calling an LLM) is intentionally
# unmetered — it cannot run away with cost.
_CLARIFY_PATH_RE = re.compile(r"^/workspaces/[^/]+/clarify/?$")
_CLARIFY_LIMIT = 6
_CLARIFY_WINDOW_SECONDS = 3600
_CLARIFY_DETAIL = "Clarification rate limit reached. Maximum 6 calls per hour."

# PDF export tier (Phase 14, T-USE-07): 10 PDF renders per user per hour.
# Applies to POST /workspaces/{id}/export/pdf only — ZIP and GitHub exports
# have their own tiers (or none at all, for ZIP).
_PDF_EXPORT_PATH_RE = re.compile(r"^/workspaces/[^/]+/export/pdf/?$")
_PDF_EXPORT_LIMIT = 10
_PDF_EXPORT_WINDOW_SECONDS = 3600
_PDF_EXPORT_DETAIL = "PDF export rate limit reached. Maximum 10 exports per hour."

# Public view tier (Phase 14, T-USE-09): 120 reads/IP/minute on /public/{slug}.
# The endpoint is unauthenticated, so we key on the client IP rather than a
# user_id. A higher per-minute cap than the per-user tiers is intentional —
# legitimate readers refreshing a shared spec must not get rate-limited.
_PUBLIC_VIEW_PATH_RE = re.compile(r"^/public/[^/]+/?$")
_PUBLIC_VIEW_LIMIT = 120
_PUBLIC_VIEW_WINDOW_SECONDS = 60
_PUBLIC_VIEW_DETAIL = "Too many requests."

# Share toggle tier (Phase 14, T-USE-09): 20 enable/disable/rotate calls per
# user per hour. Stops a script from churning a workspace's public URL.
_SHARE_TOGGLE_PATH_RE = re.compile(r"^/workspaces/[^/]+/share(?:/rotate)?/?$")
_SHARE_TOGGLE_LIMIT = 20
_SHARE_TOGGLE_WINDOW_SECONDS = 3600
_SHARE_TOGGLE_DETAIL = "Share toggle rate limit reached. Maximum 20 changes per hour."

# Billing checkout tier (Phase 18): 5 checkout sessions per user per hour.
# Prevents mass session creation that inflates Stripe API costs and
# triggers Stripe fraud detection.  T-231/T-233 — Phase 18.
_BILLING_CHECKOUT_PATH_RE = re.compile(r"^/billing/checkout/?$")
_BILLING_CHECKOUT_LIMIT = 5
_BILLING_CHECKOUT_WINDOW_SECONDS = 3600
_BILLING_CHECKOUT_DETAIL = "Checkout rate limit reached. Maximum 5 purchases per hour."

IpNetwork = IPv4Network | IPv6Network
RateLimitCheck = Callable[[str, int, int], Awaitable[bool]]

# Lua script: atomically checks the sliding window count BEFORE adding the
# new member. Returns 1 (allowed) or 0 (rejected). Because the ZCARD check
# happens before ZADD inside a single Lua call, no two concurrent requests
# can both read "count < limit" and then both write past the limit.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_start = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local ttl = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
local count = redis.call('ZCARD', key)
if count >= limit then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, ttl)
return 1
"""


async def sliding_window_check(
    redis_client: Redis,
    key: str,
    limit: int,
    window_seconds: int,
) -> bool:
    now = time.time()
    window_start = now - window_seconds
    ratelimit_key = f"ratelimit:{key}"
    member = str(time.time_ns())

    result = await redis_client.eval(
        _SLIDING_WINDOW_LUA,
        1,
        ratelimit_key,
        str(now),
        str(window_start),
        str(limit),
        member,
        str(window_seconds),
    )
    return bool(result)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        trusted_proxy_ips: str | None = None,
    ) -> None:
        super().__init__(app)
        configured_proxies = (
            settings.trusted_proxy_ips
            if trusted_proxy_ips is None
            else trusted_proxy_ips
        )
        self._trusted_proxy_networks = _parse_trusted_proxy_networks(configured_proxies)
        self._local_fallback_windows: dict[str, list[float]] = {}
        # Suppresses repeated startup warnings emitted when app.state.redis is
        # not yet populated (early lifespan, before _initialize_redis runs).
        # GIL-protected bool; no explicit lock needed.  HF-5 — T-202.
        self._redis_warned: bool = False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = _get_client_ip(request, self._trusted_proxy_networks)
        path = request.url.path

        if path in _BYPASS_PATHS:
            return await call_next(request)

        # Read Redis from the shared app-state pool injected by the FastAPI
        # lifespan (_initialize_redis).  Using request.app.state avoids
        # constructor-time Redis.from_url(), which would create an unregistered
        # connection pool that bypasses the lifespan's cleanup and also makes
        # the middleware untestable without a live Redis URL.  HF-5 — T-202.
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            if not self._redis_warned:
                logger.warning(
                    "rate_limit.redis_not_ready "
                    "falling back to in-process rate limiting"
                )
                self._redis_warned = True
            limited_response = await self._enforce_limits(
                request, ip, path, self._local_fallback_check
            )
            if limited_response is not None:
                return limited_response
            return await call_next(request)
        else:
            self._redis_warned = False  # Reset; re-fire warning on next Redis gap.

        async def _redis_check(key: str, limit: int, window_seconds: int) -> bool:
            return await sliding_window_check(redis, key, limit, window_seconds)

        try:
            limited_response = await self._enforce_limits(
                request,
                ip,
                path,
                _redis_check,
            )
        except RedisError:
            logger.warning("rate_limit.redis_unavailable_fallback", exc_info=True)
            limited_response = await self._enforce_limits(
                request,
                ip,
                path,
                self._local_fallback_check,
            )

        if limited_response is not None:
            return limited_response

        return await call_next(request)

    async def _local_fallback_check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> bool:
        return _local_sliding_window_check(
            self._local_fallback_windows,
            key,
            limit,
            window_seconds,
        )

    async def _enforce_limits(
        self,
        request: Request,
        ip: str,
        path: str,
        check: RateLimitCheck,
    ) -> Response | None:
        if not await check(f"ip:{ip}", 1000, 60):
            return _rate_limited(60)

        # T-USE-09: per-IP cap on /public/{slug}. Sits before the general
        # per-user check because the endpoint is unauthenticated.
        if request.method == "GET" and _PUBLIC_VIEW_PATH_RE.match(path):
            if not await check(
                f"public_view:{ip}",
                _PUBLIC_VIEW_LIMIT,
                _PUBLIC_VIEW_WINDOW_SECONDS,
            ):
                return _rate_limited(_PUBLIC_VIEW_WINDOW_SECONDS)

        if path in _LOGIN_PATHS:
            if not await check(
                f"login:{ip}",
                _positive_int(
                    settings.auth_login_burst_limit,
                    _LOGIN_BURST_LIMIT,
                ),
                _positive_int(
                    settings.auth_login_burst_window_seconds,
                    _LOGIN_BURST_WINDOW_SECONDS,
                ),
            ):
                return _rate_limited(
                    _positive_int(
                        settings.auth_login_burst_window_seconds,
                        _LOGIN_BURST_WINDOW_SECONDS,
                    )
                )
            if not await check(
                f"login_hourly:{ip}",
                _positive_int(
                    settings.auth_login_hourly_limit,
                    _LOGIN_HOURLY_LIMIT,
                ),
                _positive_int(
                    settings.auth_login_hourly_window_seconds,
                    _LOGIN_HOURLY_WINDOW_SECONDS,
                ),
            ):
                return _rate_limited(
                    _positive_int(
                        settings.auth_login_hourly_window_seconds,
                        _LOGIN_HOURLY_WINDOW_SECONDS,
                    )
                )

        user_id, claims = _extract_user_id(request)
        if claims is not None:
            request.state.jwt_claims = claims
        if user_id and not await check(f"user:{user_id}", 100, 60):
            return _rate_limited(60)

        if user_id and request.method == "POST" and _GITHUB_EXPORT_PATH_RE.match(path):
            allowed = await check(
                f"github_export:{user_id}",
                _GITHUB_EXPORT_LIMIT,
                _GITHUB_EXPORT_WINDOW_SECONDS,
            )
            if not allowed:
                return _rate_limited_custom(
                    detail=_GITHUB_EXPORT_DETAIL,
                    retry_after_seconds=_GITHUB_EXPORT_WINDOW_SECONDS,
                )

        if user_id and request.method == "POST" and _CLARIFY_PATH_RE.match(path):
            allowed = await check(
                f"clarify:{user_id}",
                _CLARIFY_LIMIT,
                _CLARIFY_WINDOW_SECONDS,
            )
            if not allowed:
                return _rate_limited_custom(
                    detail=_CLARIFY_DETAIL,
                    retry_after_seconds=_CLARIFY_WINDOW_SECONDS,
                )

        if user_id and request.method == "POST" and _PDF_EXPORT_PATH_RE.match(path):
            allowed = await check(
                f"pdf_export:{user_id}",
                _PDF_EXPORT_LIMIT,
                _PDF_EXPORT_WINDOW_SECONDS,
            )
            if not allowed:
                return _rate_limited_custom(
                    detail=_PDF_EXPORT_DETAIL,
                    retry_after_seconds=_PDF_EXPORT_WINDOW_SECONDS,
                )

        # T-USE-09: per-user cap on enable/disable/rotate. Catches POST and
        # DELETE on both /share and /share/rotate.
        if (
            user_id
            and request.method in ("POST", "DELETE")
            and _SHARE_TOGGLE_PATH_RE.match(path)
        ):
            allowed = await check(
                f"share_toggle:{user_id}",
                _SHARE_TOGGLE_LIMIT,
                _SHARE_TOGGLE_WINDOW_SECONDS,
            )
            if not allowed:
                return _rate_limited_custom(
                    detail=_SHARE_TOGGLE_DETAIL,
                    retry_after_seconds=_SHARE_TOGGLE_WINDOW_SECONDS,
                )

        if (
            user_id
            and request.method == "POST"
            and _BILLING_CHECKOUT_PATH_RE.match(path)
        ):
            allowed = await check(
                f"billing_checkout:{user_id}",
                _BILLING_CHECKOUT_LIMIT,
                _BILLING_CHECKOUT_WINDOW_SECONDS,
            )
            if not allowed:
                # TODO T-236: increment BILLING_CHECKOUT_RATE_LIMITED counter
                return _rate_limited_custom(
                    detail=_BILLING_CHECKOUT_DETAIL,
                    retry_after_seconds=_BILLING_CHECKOUT_WINDOW_SECONDS,
                )
        return None


def _local_sliding_window_check(
    windows: dict[str, list[float]],
    key: str,
    limit: int,
    window_seconds: int,
) -> bool:
    now = time.time()
    window_start = now - window_seconds
    ratelimit_key = f"ratelimit:{key}"
    timestamps = [ts for ts in windows.get(ratelimit_key, []) if ts > window_start]
    if len(timestamps) >= limit:
        windows[ratelimit_key] = timestamps
        return False

    timestamps.append(now)
    windows[ratelimit_key] = timestamps
    if len(windows) > _LOCAL_FALLBACK_MAX_KEYS:
        # Bulk-evict the oldest _LOCAL_FALLBACK_EVICT_BATCH entries so that a
        # burst of distinct IPs does not require O(n) individual pops.
        # itertools.islice over a dict yields keys in insertion order.
        # M-2 — T-184.
        to_delete = list(itertools.islice(windows, _LOCAL_FALLBACK_EVICT_BATCH))
        for k in to_delete:
            del windows[k]
    return True


def _positive_int(value: int, default: int) -> int:
    return value if value > 0 else default


def _get_client_ip(
    request: Request,
    trusted_proxy_networks: tuple[IpNetwork, ...] = (),
) -> str:
    client_host = request.client.host if request.client else ""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and _is_trusted_proxy(client_host, trusted_proxy_networks):
        forwarded_ip = _first_forwarded_ip(forwarded)
        if forwarded_ip:
            return forwarded_ip
    if client_host:
        return client_host
    return "unknown"


def _parse_trusted_proxy_networks(value: str) -> tuple[IpNetwork, ...]:
    networks = []
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            network = ip_network(entry, strict=False)
        except ValueError:
            continue
        if network.prefixlen == 0:
            raise ValueError(
                "trusted_proxy_ips must not include universal trust ranges"
            )
        networks.append(network)
    return tuple(networks)


def _is_trusted_proxy(host: str, trusted_proxy_networks: tuple[IpNetwork, ...]) -> bool:
    if not host or not trusted_proxy_networks:
        return False
    try:
        client_ip = ip_address(host)
    except ValueError:
        return False
    return any(client_ip in network for network in trusted_proxy_networks)


def _first_forwarded_ip(forwarded: str) -> str | None:
    candidate = forwarded.split(",", 1)[0].strip()
    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def _extract_user_id(request: Request) -> tuple[str | None, dict | None]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, None
    token = auth_header.removeprefix("Bearer ").strip()
    claims = decode_access_token_claims(token)
    if claims is None:
        return None, None
    return claims.get("sub"), claims


def _rate_limited(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Rate limit exceeded"},
        headers={"Retry-After": str(retry_after)},
    )


def _rate_limited_custom(*, detail: str, retry_after_seconds: int) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": detail},
        headers={"Retry-After": str(retry_after_seconds)},
    )

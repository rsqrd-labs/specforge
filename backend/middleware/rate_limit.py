import logging
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
        redis_client: Redis | None = None,
        trusted_proxy_ips: str | None = None,
    ) -> None:
        super().__init__(app)
        self._redis: Redis = redis_client or Redis.from_url(
            settings.redis_url, decode_responses=True
        )
        configured_proxies = (
            settings.trusted_proxy_ips
            if trusted_proxy_ips is None
            else trusted_proxy_ips
        )
        self._trusted_proxy_networks = _parse_trusted_proxy_networks(configured_proxies)
        self._local_fallback_windows: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = _get_client_ip(request, self._trusted_proxy_networks)
        path = request.url.path

        if path in _BYPASS_PATHS:
            return await call_next(request)

        try:
            limited_response = await self._enforce_limits(
                request,
                ip,
                path,
                self._redis_check,
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

    async def _redis_check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> bool:
        return await sliding_window_check(self._redis, key, limit, window_seconds)

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

        if path in _LOGIN_PATHS:
            if not await check(f"login:{ip}", 5, 300):
                return _rate_limited(300)
            if not await check(f"login_hourly:{ip}", 20, 3600):
                return _rate_limited(3600)

        user_id, claims = _extract_user_id(request)
        if claims is not None:
            request.state.jwt_claims = claims
        if user_id and not await check(f"user:{user_id}", 100, 60):
            return _rate_limited(60)
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
        windows.pop(next(iter(windows)))
    return True


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

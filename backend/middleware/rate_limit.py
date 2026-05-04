import time
from collections.abc import Callable
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from fastapi import status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings
from services.auth_service import decode_access_token_claims

_LOGIN_PATHS = frozenset({"/auth/google", "/auth/callback"})
IpNetwork = IPv4Network | IPv6Network


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

    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(ratelimit_key, "-inf", window_start)
    pipe.zadd(ratelimit_key, {member: now})
    pipe.zcard(ratelimit_key)
    pipe.expire(ratelimit_key, window_seconds)
    results = await pipe.execute()
    count = results[2]
    return count <= limit


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

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = _get_client_ip(request, self._trusted_proxy_networks)
        path = request.url.path

        if not await sliding_window_check(self._redis, f"ip:{ip}", 1000, 60):
            return _rate_limited(60)

        if path in _LOGIN_PATHS:
            if not await sliding_window_check(self._redis, f"login:{ip}", 5, 300):
                return _rate_limited(300)
            if not await sliding_window_check(
                self._redis, f"login_hourly:{ip}", 20, 3600
            ):
                return _rate_limited(3600)

        user_id, claims = _extract_user_id(request)
        if claims is not None:
            request.state.jwt_claims = claims
        if user_id:
            if not await sliding_window_check(self._redis, f"user:{user_id}", 100, 60):
                return _rate_limited(60)

        return await call_next(request)


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
            networks.append(ip_network(entry, strict=False))
        except ValueError:
            continue
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

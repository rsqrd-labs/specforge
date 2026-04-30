import time
from collections.abc import Callable

from fastapi import status
from fastapi.responses import JSONResponse
from jose import jwt as jose_jwt
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings

_LOGIN_PATHS = frozenset({"/auth/google", "/auth/callback"})


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
    def __init__(self, app, redis_client: Redis | None = None) -> None:
        super().__init__(app)
        self._redis: Redis = redis_client or Redis.from_url(
            settings.redis_url, decode_responses=True
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = _get_client_ip(request)
        path = request.url.path

        if not await sliding_window_check(self._redis, f"ip:{ip}", 1000, 60):
            return _rate_limited(60)

        if path in _LOGIN_PATHS:
            if not await sliding_window_check(self._redis, f"login:{ip}", 5, 300):
                return _rate_limited(300)

        user_id = _extract_user_id(request)
        if user_id:
            if not await sliding_window_check(self._redis, f"user:{user_id}", 100, 60):
                return _rate_limited(60)

        return await call_next(request)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _extract_user_id(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        claims = jose_jwt.get_unverified_claims(token)
        return claims.get("sub")
    except Exception:
        return None


def _rate_limited(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Rate limit exceeded"},
        headers={"Retry-After": str(retry_after)},
    )

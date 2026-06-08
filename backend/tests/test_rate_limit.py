from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError

from middleware import rate_limit as rate_limit_module
from middleware.rate_limit import (
    RateLimitMiddleware,
    _local_sliding_window_check,
    _parse_trusted_proxy_networks,
    sliding_window_check,
)


class _FakeRedis:
    """In-memory Redis stub implementing eval() with Lua sliding-window semantics."""

    def __init__(self) -> None:
        self._sets: dict[str, dict[str, float]] = {}

    async def eval(self, script: str, num_keys: int, *args: Any) -> int:
        # args order matches _SLIDING_WINDOW_LUA KEYS/ARGV:
        #   args[0]=key, args[1]=now, args[2]=window_start,
        #   args[3]=limit, args[4]=member, args[5]=ttl
        key = args[0]
        window_start = float(args[2])
        limit = int(args[3])
        member = args[4]
        now_score = float(args[1])

        ss = self._sets.setdefault(key, {})
        # Remove only strictly older entries; keep score == window_start
        expired = [m for m, s in ss.items() if s < window_start]
        for m in expired:
            del ss[m]
        # ZCARD → conditional ZADD
        if len(ss) >= limit:
            return 0
        ss[member] = now_score
        return 1

    # Keep pipeline() so harness stubs that still use the old API don't crash
    def pipeline(self) -> "_FakePipeline":
        return _FakePipeline(self)

    def _zremrangebyscore(self, key: str, min_val: Any, max_val: Any) -> int:
        ss = self._sets.get(key, {})
        min_f = float("-inf") if str(min_val) == "-inf" else float(min_val)
        max_f = float("inf") if str(max_val) == "+inf" else float(max_val)
        to_remove = [m for m, s in ss.items() if min_f <= s <= max_f]
        for m in to_remove:
            del ss[m]
        return len(to_remove)

    def _zadd(self, key: str, mapping: dict[str, float]) -> int:
        ss = self._sets.setdefault(key, {})
        added = sum(1 for m in mapping if m not in ss)
        ss.update(mapping)
        return added

    def _zcard(self, key: str) -> int:
        return len(self._sets.get(key, {}))


class _FailingRedis:
    async def eval(self, *args: Any, **kwargs: Any) -> int:
        raise RedisError("redis unavailable")


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple] = []

    def zremrangebyscore(self, key: str, min_val: Any, max_val: Any) -> "_FakePipeline":
        self._ops.append(("zremrangebyscore", key, min_val, max_val))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> "_FakePipeline":
        self._ops.append(("zadd", key, mapping))
        return self

    def zcard(self, key: str) -> "_FakePipeline":
        self._ops.append(("zcard", key))
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        self._ops.append(("expire", key, seconds))
        return self

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            cmd, *args = op
            if cmd == "zremrangebyscore":
                results.append(self._redis._zremrangebyscore(*args))
            elif cmd == "zadd":
                results.append(self._redis._zadd(*args))
            elif cmd == "zcard":
                results.append(self._redis._zcard(*args))
            elif cmd == "expire":
                results.append(1)
        return results


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.mark.asyncio
async def test_sliding_window_check_under_limit_returns_true(
    fake_redis: _FakeRedis,
) -> None:
    result = await sliding_window_check(fake_redis, "test_key", 5, 60)
    assert result is True


@pytest.mark.asyncio
async def test_sliding_window_check_over_limit_returns_false(
    fake_redis: _FakeRedis,
) -> None:
    for _ in range(5):
        await sliding_window_check(fake_redis, "test_key", 5, 60)

    result = await sliding_window_check(fake_redis, "test_key", 5, 60)
    assert result is False


@pytest.mark.asyncio
async def test_sliding_window_check_resets_after_window_expires(
    fake_redis: _FakeRedis,
) -> None:
    old_ts = time.time() - 120
    for i in range(5):
        fake_redis._sets.setdefault("ratelimit:test_key", {})[f"old_{i}"] = old_ts

    result = await sliding_window_check(fake_redis, "test_key", 5, 60)
    assert result is True


@pytest.mark.asyncio
async def test_sliding_window_check_is_atomic_does_not_exceed_limit() -> None:
    """The Lua-based check must never let count exceed the configured limit.

    With the old pipeline approach, N concurrent requests could all read
    count < limit and all write past it. The Lua script prevents this:
    the (limit+1)th call must be rejected even if it races the limit-th.
    """
    fake_redis = _FakeRedis()
    limit = 3
    # Fill to exactly the limit
    for _ in range(limit):
        allowed = await sliding_window_check(fake_redis, "burst_key", limit, 60)
        assert allowed is True

    # The next request must be rejected
    rejected = await sliding_window_check(fake_redis, "burst_key", limit, 60)
    assert rejected is False

    # Confirm the stored count is exactly the limit, not limit+1
    actual_count = len(fake_redis._sets.get("ratelimit:burst_key", {}))
    assert actual_count == limit


@pytest.mark.asyncio
async def test_rate_limit_middleware_returns_429_when_ip_limit_exceeded() -> None:
    fake_redis = _FakeRedis()
    now = time.time()
    entries = {f"req_{i}": now - i * 0.001 for i in range(1000)}
    fake_redis._sets["ratelimit:ip:203.0.113.10"] = entries

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = fake_redis

    @app.get("/")
    async def root() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"X-Forwarded-For": "203.0.113.10"})

    assert response.status_code == 429
    assert "Retry-After" in response.headers


@pytest.mark.asyncio
async def test_rate_limit_middleware_allows_20th_hourly_login_attempt() -> None:
    fake_redis = _FakeRedis()
    now = time.time()
    LOGIN_ATTEMPT_AGE_OFFSET_SECONDS = 600
    fake_redis._sets["ratelimit:login_hourly:203.0.113.10"] = {
        f"login_{i}": now - LOGIN_ATTEMPT_AGE_OFFSET_SECONDS - i for i in range(19)
    }

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = fake_redis

    @app.post("/auth/google")
    async def google_login() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/google", headers={"X-Forwarded-For": "203.0.113.10"}
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_blocks_21st_hourly_login_attempt() -> None:
    fake_redis = _FakeRedis()
    now = time.time()
    fake_redis._sets["ratelimit:login_hourly:203.0.113.10"] = {
        f"login_{i}": now - 600 - i for i in range(20)
    }

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = fake_redis

    @app.post("/auth/google")
    async def google_login() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/google", headers={"X-Forwarded-For": "203.0.113.10"}
        )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"


@pytest.mark.asyncio
async def test_rate_limit_middleware_ignores_spoofed_forwarded_for_by_default() -> None:
    fake_redis = _FakeRedis()
    now = time.time()
    fake_redis._sets["ratelimit:ip:203.0.113.10"] = {
        f"req_{i}": now - i * 0.001 for i in range(1000)
    }

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    app.state.redis = fake_redis

    @app.get("/")
    async def root() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"X-Forwarded-For": "203.0.113.10"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_ignores_malformed_forwarded_for() -> None:
    fake_redis = _FakeRedis()
    now = time.time()
    fake_redis._sets["ratelimit:ip:not-an-ip"] = {
        f"req_{i}": now - i * 0.001 for i in range(1000)
    }

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = fake_redis

    @app.get("/")
    async def root() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"X-Forwarded-For": "not-an-ip"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_uses_local_fallback_when_redis_fails() -> None:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = _FailingRedis()

    @app.get("/")
    async def root() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"X-Forwarded-For": "203.0.113.10"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_middleware_fails_open_when_redis_not_in_app_state() -> None:
    """Requests pass through when app.state.redis is not yet populated.

    During early startup (before the lifespan registers Redis) there is no
    Redis on app.state.  The middleware must not block traffic in that window:
    it logs a once-per-restart warning and lets the request through.
    HF-5 — T-202.
    """
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    # Deliberately do NOT set app.state.redis — simulates pre-lifespan state.

    @app.get("/")
    async def root() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/", headers={"X-Forwarded-For": "203.0.113.10"})

    assert response.status_code == 200, (
        "Middleware must fail open (pass request) when app.state.redis is not set. "
        "HF-5 — T-202."
    )


def test_local_fallback_limiter_blocks_over_limit() -> None:
    windows: dict[str, list[float]] = {}
    assert _local_sliding_window_check(windows, "ip:203.0.113.10", 2, 60) is True
    assert _local_sliding_window_check(windows, "ip:203.0.113.10", 2, 60) is True
    assert _local_sliding_window_check(windows, "ip:203.0.113.10", 2, 60) is False


def test_trusted_proxy_config_rejects_ipv4_universal_trust() -> None:
    with pytest.raises(ValueError, match="universal trust"):
        _parse_trusted_proxy_networks("0.0.0.0/0")


def test_trusted_proxy_config_rejects_ipv6_universal_trust() -> None:
    with pytest.raises(ValueError, match="universal trust"):
        _parse_trusted_proxy_networks("::/0")


def _fill_window(
    fake_redis: _FakeRedis,
    key: str,
    limit: int,
    *,
    age_seconds: float = 1.0,
) -> None:
    now = time.time()
    fake_redis._sets[f"ratelimit:{key}"] = {
        f"req_{i}": now - age_seconds - i * 0.001 for i in range(limit)
    }


async def _rate_limited_request(
    *,
    method: str,
    path: str,
    fake_redis: _FakeRedis,
    user_id: str | None = None,
) -> Any:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = fake_redis

    @app.api_route("/{rest:path}", methods=["GET", "POST", "DELETE"])
    async def catch_all(rest: str) -> dict:
        return {"ok": True, "path": rest}

    headers = {"X-Forwarded-For": "203.0.113.10"}
    if user_id is not None:
        headers["Authorization"] = "Bearer storyboard-token"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


@pytest.mark.asyncio
async def test_storyboard_generate_rate_limit_blocks_fourth_full_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "user-storyboard-generate"
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, f"storyboard_generate:{user_id}", 3)
    monkeypatch.setattr(
        rate_limit_module,
        "decode_access_token_claims",
        lambda token: {"sub": user_id} if token == "storyboard-token" else None,
    )

    response = await _rate_limited_request(
        method="POST",
        path="/workspaces/workspace-1/storyboards",
        fake_redis=fake_redis,
        user_id=user_id,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "3 full generations" in response.json()["detail"]


@pytest.mark.asyncio
async def test_storyboard_section_regenerate_rate_limit_blocks_eleventh_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "user-storyboard-section"
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, f"storyboard_section_regenerate:{user_id}", 10)
    monkeypatch.setattr(
        rate_limit_module,
        "decode_access_token_claims",
        lambda token: {"sub": user_id} if token == "storyboard-token" else None,
    )

    response = await _rate_limited_request(
        method="POST",
        path="/storyboards/storyboard-1/sections/technical-architecture/regenerate",
        fake_redis=fake_redis,
        user_id=user_id,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "10 sections" in response.json()["detail"]


@pytest.mark.asyncio
async def test_storyboard_share_toggle_rate_limit_blocks_twenty_first_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "user-storyboard-share"
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, f"storyboard_share_toggle:{user_id}", 20)
    monkeypatch.setattr(
        rate_limit_module,
        "decode_access_token_claims",
        lambda token: {"sub": user_id} if token == "storyboard-token" else None,
    )

    response = await _rate_limited_request(
        method="POST",
        path="/storyboards/storyboard-1/share/rotate",
        fake_redis=fake_redis,
        user_id=user_id,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "20 changes" in response.json()["detail"]


@pytest.mark.asyncio
async def test_storyboard_public_view_rate_limit_is_per_ip() -> None:
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, "storyboard_public_view:203.0.113.10", 120)

    response = await _rate_limited_request(
        method="GET",
        path="/storyboards/public/sharetoken123",
        fake_redis=fake_redis,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert "public views" in response.json()["detail"]


@pytest.mark.asyncio
async def test_storyboard_public_download_rate_limit_is_per_ip() -> None:
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, "storyboard_download_ip:203.0.113.10", 30)

    response = await _rate_limited_request(
        method="GET",
        path="/storyboards/public/sharetoken123/download/pdf",
        fake_redis=fake_redis,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "30 downloads" in response.json()["detail"]


@pytest.mark.asyncio
async def test_storyboard_owner_download_rate_limit_is_per_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "user-storyboard-download"
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, f"storyboard_download_user:{user_id}", 30)
    monkeypatch.setattr(
        rate_limit_module,
        "decode_access_token_claims",
        lambda token: {"sub": user_id} if token == "storyboard-token" else None,
    )

    response = await _rate_limited_request(
        method="GET",
        path="/storyboards/storyboard-1/download/pdf",
        fake_redis=fake_redis,
        user_id=user_id,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "30 downloads" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GitHub Sync + Increment Push tiers (Phase 21 — T-283)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["resync", "backfill"])
async def test_github_sync_rate_limit_blocks_eleventh_call(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    user_id = "user-github-sync"
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, f"github_sync:{user_id}", 10)
    monkeypatch.setattr(
        rate_limit_module,
        "decode_access_token_claims",
        lambda token: {"sub": user_id} if token == "storyboard-token" else None,
    )

    response = await _rate_limited_request(
        method="POST",
        path=f"/workspaces/workspace-1/sync/{action}",
        fake_redis=fake_redis,
        user_id=user_id,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "10 resync/backfill" in response.json()["detail"]


@pytest.mark.asyncio
async def test_github_sync_state_read_is_not_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live panel polls GET /sync; it must not share the resync/backfill cap."""
    user_id = "user-github-sync-read"
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, f"github_sync:{user_id}", 10)
    monkeypatch.setattr(
        rate_limit_module,
        "decode_access_token_claims",
        lambda token: {"sub": user_id} if token == "storyboard-token" else None,
    )

    response = await _rate_limited_request(
        method="GET",
        path="/workspaces/workspace-1/sync",
        fake_redis=fake_redis,
        user_id=user_id,
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_github_increment_push_rate_limit_blocks_sixth_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "user-github-increment"
    fake_redis = _FakeRedis()
    _fill_window(fake_redis, f"github_increment_push:{user_id}", 5)
    monkeypatch.setattr(
        rate_limit_module,
        "decode_access_token_claims",
        lambda token: {"sub": user_id} if token == "storyboard-token" else None,
    )

    response = await _rate_limited_request(
        method="POST",
        path="/workspaces/workspace-1/increments/inc-1/push",
        fake_redis=fake_redis,
        user_id=user_id,
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "5 pushes" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_not_blocked_by_generic_ip_cap() -> None:
    """A provider's redelivery burst above the generic 1000/min IP cap must NOT
    be throttled on the webhook path (LF-1 review remediation).

    The generic ``ip:`` window is pre-loaded past its 1000 limit; a webhook POST
    from that IP must still pass, because webhook ingress uses only the separate,
    generous ``webhook_ip`` backstop — never the generic per-IP cap.
    """
    fake_redis = _FakeRedis()
    now = time.time()
    fake_redis._sets["ratelimit:ip:203.0.113.50"] = {
        f"req_{i}": now - i * 0.001 for i in range(1500)
    }

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = fake_redis

    @app.post("/integrations/github/webhook")
    async def webhook() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/integrations/github/webhook",
            headers={"X-Forwarded-For": "203.0.113.50"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_flood_backstop_blocks_single_ip() -> None:
    """A single-source flood beyond the webhook backstop is rejected (LF-1).

    Pre-loading the ``webhook_ip`` window to its limit makes the next webhook POST
    from that IP a 429 — blunting a bogus-delivery flood before the HMAC check.
    """
    fake_redis = _FakeRedis()
    now = time.time()
    fake_redis._sets["ratelimit:webhook_ip:203.0.113.51"] = {
        f"hit_{i}": now - i * 0.001 for i in range(6000)
    }

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, trusted_proxy_ips="127.0.0.1")
    app.state.redis = fake_redis

    @app.post("/billing/webhook")
    async def webhook() -> dict:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/billing/webhook",
            headers={"X-Forwarded-For": "203.0.113.51"},
        )

    assert response.status_code == 429
    assert "Retry-After" in response.headers

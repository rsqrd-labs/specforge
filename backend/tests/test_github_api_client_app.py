"""Unit tests for the GitHub App (installation-token) mode of GitHubAPIClient
and its circuit breaker (T-268).

httpx.MockTransport drives deterministic response sequences; a fake token
source stands in for the T-267 TokenProvider so per-call resolution and the
single-re-mint-on-401 behaviour are observable without Redis or GitHub.
"""

from __future__ import annotations

import httpx
import pytest

from services.integrations.github_api_client import (
    GitHubAPIClient,
    GitHubAPIError,
    GitHubCircuitBreaker,
    GitHubTokenExpiredError,
    GitHubUnavailableError,
    make_app_github_client,
    make_shared_async_client,
)


class _FakeTokenSource:
    """Counts get/refresh calls and hands out a monotonically changing token."""

    def __init__(self) -> None:
        self.get_calls = 0
        self.refresh_calls = 0
        self._n = 0

    async def get(self, installation_id: int) -> str:
        self.get_calls += 1
        if self._n == 0:
            self._n = 1
        return f"tok-{self._n}"

    async def refresh(self, installation_id: int) -> str:
        self.refresh_calls += 1
        self._n += 1
        return f"tok-{self._n}"


def _client(handler, source: _FakeTokenSource, **kw) -> GitHubAPIClient:
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    return make_app_github_client(source, 42, async_client, **kw)


# ---------------------------------------------------------------------------
# Per-call token resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_resolved_per_call_not_in_init() -> None:
    source = _FakeTokenSource()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        return httpx.Response(201, json={"number": 1})

    client = _client(handler, source)
    # Constructing the client must not resolve a token.
    assert source.get_calls == 0

    await client.create_issue("o/r", "t", "b")
    await client.create_issue("o/r", "t", "b")
    # Each request resolved a token (no static token held).
    assert source.get_calls == 2
    assert seen == ["Bearer tok-1", "Bearer tok-1"]


# ---------------------------------------------------------------------------
# Re-mint once on 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_remints_token_on_401_once() -> None:
    source = _FakeTokenSource()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        # First attempt: token rotated under us → 401. Retry: success.
        if calls["n"] == 1:
            assert request.headers["Authorization"] == "Bearer tok-1"
            return httpx.Response(401, json={"message": "Bad credentials"})
        assert request.headers["Authorization"] == "Bearer tok-2"
        return httpx.Response(201, json={"number": 7})

    client = _client(handler, source)
    number = await client.create_issue("o/r", "t", "b")

    assert number == 7
    assert source.refresh_calls == 1  # re-minted exactly once
    assert calls["n"] == 2  # one retry only


@pytest.mark.asyncio
async def test_second_401_raises_token_expired() -> None:
    source = _FakeTokenSource()

    def handler(request: httpx.Request) -> httpx.Response:
        # Always 401 — even the re-minted token fails.
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = _client(handler, source)
    with pytest.raises(GitHubTokenExpiredError):
        await client.create_issue("o/r", "t", "b")

    # Exactly one re-mint attempt — SpecForge never loops on an invalid token.
    assert source.refresh_calls == 1


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breaker_trips_after_threshold_and_raises_unavailable() -> None:
    source = _FakeTokenSource()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    breaker = GitHubCircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)
    client = _client(handler, source, breaker=breaker)

    # Each 500 still maps to its typed error (breaker accounting is additive)…
    for _ in range(3):
        with pytest.raises(GitHubAPIError):
            await client.create_issue("o/r", "t", "b")

    # …and after the threshold the breaker is open: the next call is rejected
    # before any request is sent.
    before = source.get_calls
    with pytest.raises(GitHubUnavailableError):
        await client.create_issue("o/r", "t", "b")
    assert source.get_calls == before  # no token resolved, no request sent


@pytest.mark.asyncio
async def test_breaker_stays_closed_on_success() -> None:
    source = _FakeTokenSource()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"number": 1})

    breaker = GitHubCircuitBreaker(failure_threshold=2)
    client = _client(handler, source, breaker=breaker)
    for _ in range(5):
        await client.create_issue("o/r", "t", "b")  # never raises


@pytest.mark.asyncio
async def test_breaker_recovers_after_intermittent_failures() -> None:
    # A success resets the failure window, so sparse failures never trip the
    # breaker (threshold is consecutive-within-window, not lifetime).
    source = _FakeTokenSource()
    state = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(201, json={"number": 1})

    breaker = GitHubCircuitBreaker(failure_threshold=3)
    client = _client(handler, source, breaker=breaker)

    for _ in range(2):
        with pytest.raises(GitHubAPIError):
            await client.create_issue("o/r", "t", "b")
    state["fail"] = False
    await client.create_issue("o/r", "t", "b")  # success resets the window
    state["fail"] = True
    for _ in range(2):
        with pytest.raises(GitHubAPIError):
            await client.create_issue("o/r", "t", "b")
    # Only 2 failures since the reset (< threshold 3) — breaker still closed, so
    # a subsequent successful call goes through rather than being rejected.
    state["fail"] = False
    await client.create_issue("o/r", "t", "b")


@pytest.mark.asyncio
async def test_breaker_half_open_trial_succeeds_and_closes() -> None:
    # cooldown_seconds=0 makes the open→half-open transition deterministic
    # (monotonic time has advanced by the next call), so the half-open trial
    # path is exercised without any sleep.
    source = _FakeTokenSource()
    state = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(201, json={"number": 1})

    breaker = GitHubCircuitBreaker(failure_threshold=2, cooldown_seconds=0.0)
    client = _client(handler, source, breaker=breaker)

    for _ in range(2):
        with pytest.raises(GitHubAPIError):
            await client.create_issue("o/r", "t", "b")  # opens the breaker

    # Cooldown is 0 → next call is admitted as a half-open trial; it succeeds,
    # so the breaker closes and stays closed.
    state["fail"] = False
    await client.create_issue("o/r", "t", "b")
    await client.create_issue("o/r", "t", "b")


@pytest.mark.asyncio
async def test_breaker_half_open_trial_fails_and_reopens() -> None:
    source = _FakeTokenSource()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    breaker = GitHubCircuitBreaker(failure_threshold=2, cooldown_seconds=0.0)
    client = _client(handler, source, breaker=breaker)

    for _ in range(2):
        with pytest.raises(GitHubAPIError):
            await client.create_issue("o/r", "t", "b")  # opens

    # Half-open trial is admitted (cooldown 0) and fails → breaker re-opens. The
    # 500 still maps to GitHubAPIError on the admitted trial.
    with pytest.raises(GitHubAPIError):
        await client.create_issue("o/r", "t", "b")


@pytest.mark.asyncio
async def test_network_error_maps_to_api_error_and_counts_to_breaker() -> None:
    source = _FakeTokenSource()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    breaker = GitHubCircuitBreaker(failure_threshold=2, cooldown_seconds=30.0)
    client = _client(handler, source, breaker=breaker)

    for _ in range(2):
        with pytest.raises(GitHubAPIError) as exc:
            await client.create_issue("o/r", "t", "b")
        # The raw exception text is never interpolated — only its class name.
        assert "connection refused" not in str(exc.value)

    # Two network failures tripped the breaker.
    with pytest.raises(GitHubUnavailableError):
        await client.create_issue("o/r", "t", "b")


@pytest.mark.asyncio
async def test_make_shared_async_client_has_bounded_timeout() -> None:
    client = make_shared_async_client()
    try:
        assert client.timeout.read == 30.0
        assert client.timeout.connect == 10.0
    finally:
        await client.aclose()


def test_constructor_rejects_ambiguous_auth_sources() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async_client = httpx.AsyncClient(transport=transport)
    with pytest.raises(ValueError):
        GitHubAPIClient(
            client=async_client,
            token="static",
            token_provider=_FakeTokenSource(),  # type: ignore[arg-type]
            installation_id=1,
        )


def test_constructor_requires_installation_id_with_provider() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async_client = httpx.AsyncClient(transport=transport)
    with pytest.raises(ValueError):
        GitHubAPIClient(client=async_client, token_provider=_FakeTokenSource())  # type: ignore[arg-type]


def test_constructor_requires_some_auth_source() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async_client = httpx.AsyncClient(transport=transport)
    with pytest.raises(ValueError):
        GitHubAPIClient(client=async_client)

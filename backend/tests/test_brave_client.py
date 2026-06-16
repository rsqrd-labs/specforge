"""Phase 1 tests for the Brave LLM Context API adapter (issue #12).

The adapter's contract is "never raises, fail open to ``None`` on any failure",
so these are almost entirely negative-path tests plus the key-never-logged
assertion that backs the acceptance criteria.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from config import settings
from services.research import brave_client
from services.research.brave_client import BraveResult, fetch

_TEST_KEY = "brv-secret-subscription-token-do-not-log"

_GROUNDED_BODY = {
    "grounding": {
        "generic": [
            {
                "url": "https://example.dev/fastapi",
                "title": "FastAPI best practices 2026",
                "snippets": ["Use lifespan handlers.", "Prefer async DB drivers."],
            },
            {
                "url": "https://example.dev/empty",
                "title": "No snippets here",
                "snippets": [],  # dropped: a result with no usable snippets
            },
        ]
    },
    "sources": {
        "https://example.dev/fastapi": {
            "title": "FastAPI best practices 2026",
            "hostname": "example.dev",
            "age": "2 days ago",
        }
    },
}


@pytest.fixture(autouse=True)
def _enable_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests need a configured key; the keyless case overrides this."""
    monkeypatch.setattr(settings, "brave_search_api_key", _TEST_KEY)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_success_parses_grounding_and_sources() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["token"] = request.headers.get("X-Subscription-Token")
        captured["q"] = request.url.params.get("q")
        captured["freshness"] = request.url.params.get("freshness")
        return httpx.Response(200, json=_GROUNDED_BODY)

    async with _client(handler) as client:
        result = await fetch("FastAPI best practices", http_client=client)

    assert isinstance(result, BraveResult)
    assert not result.is_empty
    # The empty-snippet result is dropped; only the usable one survives.
    assert len(result.results) == 1
    assert result.results[0].url == "https://example.dev/fastapi"
    assert result.results[0].snippets == (
        "Use lifespan handlers.",
        "Prefer async DB drivers.",
    )
    assert len(result.sources) == 1
    assert result.sources[0].hostname == "example.dev"
    assert result.sources[0].age == "2 days ago"
    # Auth header carries the key; freshness defaults from config.
    assert captured["token"] == _TEST_KEY
    assert captured["q"] == "FastAPI best practices"
    assert captured["freshness"] == settings.brave_freshness


async def test_empty_grounding_is_empty_result_not_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"grounding": {"generic": []}})

    async with _client(handler) as client:
        result = await fetch("nothing relevant", http_client=client)

    assert isinstance(result, BraveResult)
    assert result.is_empty
    assert result.results == ()


async def test_missing_grounding_key_is_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sources": {}})

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert isinstance(result, BraveResult)
    assert result.is_empty


async def test_429_retries_once_then_returns_none() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None
    assert calls["n"] == 2  # initial + exactly one retry


async def test_5xx_retries_once_then_returns_none() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None
    assert calls["n"] == 2


async def test_429_then_success_recovers() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=_GROUNDED_BODY)

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert isinstance(result, BraveResult)
    assert not result.is_empty
    assert calls["n"] == 2


async def test_non_retryable_status_returns_none_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401)

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None
    assert calls["n"] == 1  # 4xx (non-429) is not retried


async def test_timeout_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None


async def test_connect_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None


async def test_malformed_json_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json {{{")

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None


async def test_unexpected_schema_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 2xx but grounding.generic is not a list → malformed.
        return httpx.Response(200, json={"grounding": {"generic": "nope"}})

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None


async def test_blank_key_returns_none_without_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "brave_search_api_key", "")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not issue a keyless request")

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None


async def test_blank_query_returns_none_without_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not issue a request for a blank query")

    async with _client(handler) as client:
        result = await fetch("   ", http_client=client)

    assert result is None


async def test_long_query_is_truncated_to_contract_limit() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"grounding": {"generic": []}})

    async with _client(handler) as client:
        await fetch("x" * 1000, http_client=client)

    assert isinstance(captured["q"], str)
    assert len(captured["q"]) == 400


async def test_api_key_is_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Force every log-emitting branch we control to fire.
        return httpx.Response(500)

    with caplog.at_level(logging.DEBUG, logger="services.research.brave_client"):
        async with _client(handler) as client:
            await fetch("a query that should never leak the key", http_client=client)

    combined = "\n".join(record.getMessage() for record in caplog.records)
    combined += "\n".join(str(record.__dict__) for record in caplog.records)
    assert _TEST_KEY not in combined


async def test_unexpected_error_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bug below the HTTP layer (e.g. a parser raising) must still fail open.
    def boom(payload: object, query: str) -> None:
        raise RuntimeError("parser bug")

    monkeypatch.setattr(brave_client, "_parse", boom)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_GROUNDED_BODY)

    async with _client(handler) as client:
        result = await fetch("q", http_client=client)

    assert result is None


async def test_brave_search_enabled_requires_key_and_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "brave_search_api_key", "")
    monkeypatch.setattr(settings, "brave_search_flag", False)
    assert settings.brave_search_enabled is False

    monkeypatch.setattr(settings, "brave_search_api_key", _TEST_KEY)
    assert settings.brave_search_enabled is False  # flag still off

    monkeypatch.setattr(settings, "brave_search_flag", True)
    assert settings.brave_search_enabled is True

    monkeypatch.setattr(settings, "brave_search_api_key", "")
    assert settings.brave_search_enabled is False  # key blank ⇒ off

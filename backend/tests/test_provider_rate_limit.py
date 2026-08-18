"""Provider 429/overload classification + 429-aware retry (scalability audit F2).

Covers:
  RL-1  classify_provider_status reads status_code / status / code.
  RL-2  extract_retry_after parses a numeric Retry-After, ignores junk/absent.
  RL-3  each adapter's _wrap_*_error maps 429/529/503 -> ProviderRateLimitError
        (with retry_after) and anything else -> plain ProviderError.
  RL-4  ProviderRateLimitError IS a ProviderError (every existing handler catches).
  RL-5  end-to-end: a provider RateLimitError surfaces as ProviderRateLimitError.
  RL-6  record_provider_failure does NOT trip the circuit for a rate-limit, but
        DOES increment the rate-limit meter; a normal error still trips it.
  RL-7  _rate_limit_retry_delay honors Retry-After (clamped) and otherwise backs
        off with jitter inside the configured ceiling.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest

from services.llm.base import (
    ProviderError,
    ProviderRateLimitError,
    classify_provider_status,
    extract_retry_after,
)


def _resp(status: int, *, retry_after: str | None = None) -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status, headers=headers, request=httpx.Request("POST", "http://x")
    )


# ---------------------------------------------------------------------------
# RL-1 / RL-2 — shared classifier helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "obj, expected",
    [
        (SimpleNamespace(status_code=429), 429),
        (SimpleNamespace(status=503), 503),
        (SimpleNamespace(code=429), 429),
        (SimpleNamespace(code="429"), 429),
        (SimpleNamespace(), None),
        (SimpleNamespace(status_code=True), None),  # bool is not a status
    ],
)
def test_classify_provider_status(obj, expected) -> None:
    assert classify_provider_status(obj) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5", 5.0),
        ("0", 0.0),
        ("12.5", 12.5),
        ("soon", None),
        (None, None),
        ("-3", None),
    ],
)
def test_extract_retry_after(raw, expected) -> None:
    exc = SimpleNamespace(response=_resp(429, retry_after=raw))
    assert extract_retry_after(exc) == expected


def test_extract_retry_after_no_response() -> None:
    assert extract_retry_after(SimpleNamespace()) is None


def test_extract_retry_after_accepts_http_date() -> None:
    retry_at = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    exc = SimpleNamespace(response=_resp(503, retry_after=retry_at))

    delay = extract_retry_after(exc)

    assert delay is not None
    assert 8 <= delay <= 10


# ---------------------------------------------------------------------------
# RL-3 / RL-4 — per-adapter wrappers
# ---------------------------------------------------------------------------


def test_anthropic_wrap_rate_limit() -> None:
    from services.llm.anthropic_adapter import _wrap_anthropic_error

    exc = anthropic.RateLimitError(
        "slow down", response=_resp(429, retry_after="7"), body=None
    )
    wrapped = _wrap_anthropic_error(exc)
    assert isinstance(wrapped, ProviderRateLimitError)
    assert isinstance(wrapped, ProviderError)  # RL-4
    assert wrapped.retry_after == 7.0
    assert wrapped.provider == "anthropic"


def test_anthropic_wrap_overloaded_529() -> None:
    from services.llm.anthropic_adapter import _wrap_anthropic_error

    # 529 overloaded arrives as a generic APIStatusError; the status path catches it.
    exc = anthropic.InternalServerError("overloaded", response=_resp(529), body=None)
    assert isinstance(_wrap_anthropic_error(exc), ProviderRateLimitError)


def test_anthropic_wrap_other_error_stays_plain() -> None:
    from services.llm.anthropic_adapter import _wrap_anthropic_error

    exc = anthropic.BadRequestError("bad", response=_resp(400), body=None)
    wrapped = _wrap_anthropic_error(exc)
    assert isinstance(wrapped, ProviderError)
    assert not isinstance(wrapped, ProviderRateLimitError)


def test_openai_wrap_rate_limit() -> None:
    from services.llm.openai_adapter import _wrap_openai_error

    exc = openai.RateLimitError(
        "slow down", response=_resp(429, retry_after="3"), body=None
    )
    wrapped = _wrap_openai_error(exc)
    assert isinstance(wrapped, ProviderRateLimitError)
    assert wrapped.retry_after == 3.0


def test_openai_wrap_other_error_stays_plain() -> None:
    from services.llm.openai_adapter import _wrap_openai_error

    exc = openai.BadRequestError("bad", response=_resp(400), body=None)
    assert not isinstance(_wrap_openai_error(exc), ProviderRateLimitError)


@pytest.mark.parametrize("status", [429, 503])
def test_google_wrap_rate_limit(status) -> None:
    from services.llm.google_adapter import _wrap_google_error

    exc = SimpleNamespace(code=status, response=_resp(status, retry_after="4"))
    wrapped = _wrap_google_error(exc)  # type: ignore[arg-type]
    assert isinstance(wrapped, ProviderRateLimitError)
    assert wrapped.retry_after == 4.0
    assert wrapped.provider == "google"


def test_google_wrap_other_error_stays_plain() -> None:
    from services.llm.google_adapter import _wrap_google_error

    exc = SimpleNamespace(code=400, response=_resp(400))
    wrapped = _wrap_google_error(exc)  # type: ignore[arg-type]
    assert isinstance(wrapped, ProviderError)
    assert not isinstance(wrapped, ProviderRateLimitError)


# ---------------------------------------------------------------------------
# Gemini carries its retry hint in the error BODY, never in a Retry-After header
# ---------------------------------------------------------------------------


def _gemini_429(*, retry_delay: str | None, message: str = "quota exceeded"):
    """A 429 shaped exactly like a live generativelanguage.googleapis.com reply."""
    entries: list[dict] = [
        {
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [{"quotaValue": "5"}],
        }
    ]
    if retry_delay is not None:
        entries.append(
            {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": retry_delay,
            }
        )
    return SimpleNamespace(
        code=429,
        message=message,
        details={
            "error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": entries}
        },
        response=_resp(429),  # no Retry-After header — Gemini never sets one
    )


def test_google_reads_retry_delay_from_structured_error_body() -> None:
    """Regression: Gemini sets no Retry-After header, so the header-only reader
    returned None and the pipeline retried after ~50ms against a quota window
    that stays closed for 40s — burning every retry and failing the stage."""
    from services.llm.google_adapter import _wrap_google_error

    wrapped = _wrap_google_error(_gemini_429(retry_delay="40s"))  # type: ignore[arg-type]
    assert isinstance(wrapped, ProviderRateLimitError)
    assert wrapped.retry_after == 40.0


def test_google_reads_fractional_retry_delay() -> None:
    from services.llm.google_adapter import _wrap_google_error

    wrapped = _wrap_google_error(_gemini_429(retry_delay="1.5s"))  # type: ignore[arg-type]
    assert wrapped.retry_after == 1.5  # type: ignore[union-attr]


def test_google_falls_back_to_the_delay_restated_in_the_message() -> None:
    from services.llm.google_adapter import _wrap_google_error

    exc = _gemini_429(
        retry_delay=None,
        message="You exceeded your current quota. Please retry in 40.063716105s.",
    )
    wrapped = _wrap_google_error(exc)  # type: ignore[arg-type]
    assert wrapped.retry_after == pytest.approx(40.063716105)  # type: ignore[union-attr]


def test_google_retry_after_header_wins_when_present() -> None:
    from services.llm.google_adapter import _wrap_google_error

    exc = _gemini_429(retry_delay="40s")
    exc.response = _resp(429, retry_after="7")
    wrapped = _wrap_google_error(exc)  # type: ignore[arg-type]
    assert wrapped.retry_after == 7.0  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "details",
    [
        None,
        "not-a-dict",
        {"error": "not-a-dict"},
        {"error": {"details": "not-a-list"}},
        {"error": {"details": [{"@type": "other.Type", "retryDelay": "9s"}]}},
        {"error": {"details": [{"@type": "google.rpc.RetryInfo"}]}},
        {
            "error": {
                "details": [{"@type": "google.rpc.RetryInfo", "retryDelay": "soon"}]
            }
        },
    ],
)
def test_google_malformed_hint_degrades_to_backoff(details) -> None:
    """A missing or malformed hint must never raise — it falls back to backoff."""
    from services.llm.google_adapter import _wrap_google_error

    exc = SimpleNamespace(
        code=429, message="throttled", details=details, response=_resp(429)
    )
    wrapped = _wrap_google_error(exc)  # type: ignore[arg-type]
    assert isinstance(wrapped, ProviderRateLimitError)
    assert wrapped.retry_after is None


# ---------------------------------------------------------------------------
# RL-5 — end-to-end adapter streaming surfaces ProviderRateLimitError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_stream_surfaces_rate_limit() -> None:
    from unittest.mock import MagicMock

    from services.llm.anthropic_adapter import AnthropicAdapter

    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model = "claude-haiku-4-5"
    adapter._request_policy = {"reasoning_effort": None}
    adapter.last_completion = None

    def _raise(*_a, **_k):
        raise anthropic.RateLimitError(
            "429", response=_resp(429, retry_after="9"), body=None
        )

    mock_messages = MagicMock()
    mock_messages.stream = _raise
    adapter._client = MagicMock()
    adapter._client.messages = mock_messages

    with pytest.raises(ProviderRateLimitError) as exc_info:
        async for _ in adapter.stream("sys", "user", 10):
            pass
    assert exc_info.value.retry_after == 9.0


@pytest.mark.asyncio
async def test_openai_complete_surfaces_rate_limit() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from services.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter.model = "gpt-4o"
    adapter._request_policy = {"adapter_api": "chat_completions"}
    adapter.last_completion = None

    mock_create = AsyncMock(
        side_effect=openai.RateLimitError(
            "429", response=_resp(429, retry_after="2"), body=None
        )
    )
    adapter._client = MagicMock()
    adapter._client.chat.completions.create = mock_create

    with pytest.raises(ProviderRateLimitError) as exc_info:
        await adapter.complete("sys", "user", 10)
    assert exc_info.value.retry_after == 2.0


# ---------------------------------------------------------------------------
# RL-6 — circuit breaker excludes rate limits
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_failures():
    from services.llm import provider_status

    provider_status._FAILURES.clear()
    yield
    provider_status._FAILURES.clear()


def test_rate_limit_does_not_trip_circuit() -> None:
    from services.llm import provider_status
    from services.llm.provider_status import (
        PROVIDER_RATE_LIMITED,
        can_route,
        record_provider_failure,
    )

    before = PROVIDER_RATE_LIMITED.labels(provider="anthropic")._value.get()
    rate = ProviderRateLimitError("anthropic", ValueError("429"), retry_after=5)
    # Many rate-limits in a row must never open the circuit.
    for _ in range(provider_status._UNHEALTHY_FAILURE_THRESHOLD + 2):
        record_provider_failure("anthropic", rate)
    assert can_route("anthropic") is True
    assert "anthropic" not in provider_status._FAILURES
    after = PROVIDER_RATE_LIMITED.labels(provider="anthropic")._value.get()
    assert after == before + (provider_status._UNHEALTHY_FAILURE_THRESHOLD + 2)


def test_normal_error_still_trips_circuit() -> None:
    from services.llm import provider_status
    from services.llm.provider_status import can_route, record_provider_failure

    for _ in range(provider_status._UNHEALTHY_FAILURE_THRESHOLD):
        record_provider_failure("openai", ProviderError("openai", ValueError("boom")))
    assert can_route("openai") is False


# ---------------------------------------------------------------------------
# RL-7 — backoff delay helper
# ---------------------------------------------------------------------------


def test_retry_delay_honors_retry_after(monkeypatch) -> None:
    from config import settings
    from services.pipeline import stage_manager as sm

    monkeypatch.setattr(settings, "provider_rate_limit_backoff_base_seconds", 2.0)

    # The hint is always waited out in full; a bounded additive jitter is layered
    # on top so parallel chunks handed the same hint do not wake in lockstep.
    for _ in range(50):
        delay = sm._rate_limit_retry_delay(0, 8.0)
        assert 8.0 <= delay <= 10.0
    # Clamped to the absolute cap for a pathological value.
    assert sm._rate_limit_retry_delay(0, 10_000.0) == sm._RATE_LIMIT_RETRY_AFTER_CAP


def test_retry_delay_hint_jitter_desynchronizes_parallel_chunks(monkeypatch) -> None:
    """Regression: four tasks chunks are throttled within milliseconds of each
    other and are handed near-identical hints. Returning the hint verbatim wakes
    them simultaneously and re-collides on the same quota."""
    from config import settings
    from services.pipeline import stage_manager as sm

    monkeypatch.setattr(settings, "provider_rate_limit_backoff_base_seconds", 2.0)

    delays = {sm._rate_limit_retry_delay(0, 40.0) for _ in range(40)}
    assert len(delays) > 1


def test_retry_delay_backoff_within_ceiling(monkeypatch) -> None:
    from config import settings
    from services.pipeline import stage_manager as sm

    monkeypatch.setattr(settings, "provider_rate_limit_backoff_base_seconds", 2.0)
    monkeypatch.setattr(settings, "provider_rate_limit_backoff_max_seconds", 30.0)
    # No hint -> exponential backoff with equal jitter: within [ceiling/2, ceiling].
    for attempt in range(5):
        ceiling = min(2.0 * (2**attempt), 30.0)
        for _ in range(20):
            delay = sm._rate_limit_retry_delay(attempt, None)
            assert ceiling / 2.0 <= delay <= ceiling


def test_retry_delay_never_retries_immediately(monkeypatch) -> None:
    """Regression: full jitter over [0, ceiling] returned delays as small as
    0.05s, re-firing inside the provider's still-closed quota window and burning
    the whole retry budget in a few seconds."""
    from config import settings
    from services.pipeline import stage_manager as sm

    monkeypatch.setattr(settings, "provider_rate_limit_backoff_base_seconds", 2.0)
    monkeypatch.setattr(settings, "provider_rate_limit_backoff_max_seconds", 30.0)

    for attempt in range(4):
        for _ in range(200):
            assert sm._rate_limit_retry_delay(attempt, None) >= 1.0

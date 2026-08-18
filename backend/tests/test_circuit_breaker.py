"""Unit tests for T-197 — CF-2: circuit breaker enforcement in gateway.get_llm().

Tests verify:
  CB-1  can_route() returns True for a healthy provider
  CB-2  can_route() returns False after _UNHEALTHY_FAILURE_THRESHOLD failures
  CB-3  can_route() resets to True after record_provider_success()
  CB-4  get_llm() raises HTTPException(503) when can_route() returns False
  CB-5  CIRCUIT_REJECTIONS counter is incremented on each rejection
  CB-6  bypass_circuit=True lets get_llm() skip the circuit check
  CB-7  check_provider_health() can reach a provider whose circuit is open
        (it calls get_llm(..., bypass_circuit=True))
  CB-8  circuit window expiry: failures older than _RECENT_FAILURE_WINDOW_SECONDS
        are treated as healthy
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Fixtures — isolate _FAILURES between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_circuit_state():
    """Clear provider_status._FAILURES before and after every test."""
    from services.llm import provider_status

    provider_status._FAILURES.clear()
    yield
    provider_status._FAILURES.clear()


@pytest.fixture(autouse=True)
def clear_llm_cache():
    """Clear gateway._INSTANCES before and after every test."""
    from services.llm.gateway import clear_llm_cache

    clear_llm_cache()
    yield
    clear_llm_cache()


# ---------------------------------------------------------------------------
# CB-1: healthy provider is routable
# ---------------------------------------------------------------------------


def test_can_route_healthy_provider() -> None:
    """CB-1 — can_route returns True when there are no recorded failures."""
    from services.llm.provider_status import can_route

    assert can_route("anthropic") is True
    assert can_route("openai") is True
    assert can_route("google") is True


# ---------------------------------------------------------------------------
# CB-2: circuit trips after threshold failures
# ---------------------------------------------------------------------------


def test_can_route_false_after_threshold_failures() -> None:
    """CB-2 — can_route returns False after failure threshold is reached."""
    from services.llm.provider_status import (
        _UNHEALTHY_FAILURE_THRESHOLD,
        can_route,
        record_provider_failure,
    )

    exc = RuntimeError("provider timeout")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD):
        record_provider_failure("anthropic", exc)

    assert can_route("anthropic") is False, (
        f"Expected can_route to return False after {_UNHEALTHY_FAILURE_THRESHOLD} "
        "consecutive failures (circuit threshold reached)."
    )


def test_can_route_still_true_below_threshold() -> None:
    """CB-2 — can_route returns True when failures are below the threshold."""
    from services.llm.provider_status import (
        _UNHEALTHY_FAILURE_THRESHOLD,
        can_route,
        record_provider_failure,
    )

    exc = RuntimeError("transient error")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD - 1):
        record_provider_failure("openai", exc)

    assert can_route("openai") is True, (
        "can_route must return True when failures are below the threshold "
        "(circuit should not trip on a single transient error)."
    )


# ---------------------------------------------------------------------------
# CB-3: circuit resets after a success
# ---------------------------------------------------------------------------


def test_can_route_resets_after_success() -> None:
    """CB-3 — can_route returns True again after record_provider_success() resets it."""
    from services.llm.provider_status import (
        _UNHEALTHY_FAILURE_THRESHOLD,
        can_route,
        record_provider_failure,
        record_provider_success,
    )

    exc = RuntimeError("error")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD):
        record_provider_failure("anthropic", exc)

    assert can_route("anthropic") is False, "circuit should be open before reset"
    record_provider_success("anthropic")
    assert (
        can_route("anthropic") is True
    ), "can_route must return True after record_provider_success() resets the circuit."


# ---------------------------------------------------------------------------
# CB-4: gateway raises 503 when circuit is open
# ---------------------------------------------------------------------------


def test_get_llm_raises_503_when_circuit_open() -> None:
    """CB-4 — get_llm() raises HTTPException(503) when circuit is open."""
    from services.llm.provider_status import (
        _UNHEALTHY_FAILURE_THRESHOLD,
        record_provider_failure,
    )

    exc = RuntimeError("provider down")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD):
        record_provider_failure("anthropic", exc)

    from services.llm.gateway import get_llm

    with pytest.raises(HTTPException) as exc_info:
        get_llm("anthropic", "claude-3-haiku")

    assert (
        exc_info.value.status_code == 503
    ), f"Expected HTTPException with status_code=503, got {exc_info.value.status_code}"
    assert "temporarily unavailable" in exc_info.value.detail.lower(), (
        f"503 detail must mention 'temporarily unavailable', "
        f"got: {exc_info.value.detail!r}"
    )


# ---------------------------------------------------------------------------
# CB-5: CIRCUIT_REJECTIONS counter is incremented on rejection
# ---------------------------------------------------------------------------


def test_circuit_rejections_counter_incremented() -> None:
    """CB-5 — CIRCUIT_REJECTIONS counter is incremented on each rejection."""
    from services.llm.provider_status import (
        _UNHEALTHY_FAILURE_THRESHOLD,
        CIRCUIT_REJECTIONS,
        record_provider_failure,
    )

    exc = RuntimeError("provider down")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD):
        record_provider_failure("openai", exc)

    # Read the current count before.
    before = CIRCUIT_REJECTIONS.labels(provider="openai")._value.get()

    from services.llm.gateway import get_llm

    with pytest.raises(HTTPException):
        get_llm("openai", "gpt-4o")

    after = CIRCUIT_REJECTIONS.labels(provider="openai")._value.get()
    assert after == before + 1, (
        f"Expected CIRCUIT_REJECTIONS counter to increment by 1, "
        f"got before={before} after={after}"
    )


# ---------------------------------------------------------------------------
# CB-6: bypass_circuit=True skips the circuit check
# ---------------------------------------------------------------------------


def test_get_llm_bypass_circuit_skips_check() -> None:
    """CB-6 — bypass_circuit=True lets get_llm() skip the circuit check."""
    from services.llm.provider_status import (
        _UNHEALTHY_FAILURE_THRESHOLD,
        record_provider_failure,
    )

    exc = RuntimeError("provider down")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD):
        record_provider_failure("anthropic", exc)

    from services.llm.gateway import get_llm

    # With bypass_circuit=True, no 503 should be raised.
    fake_adapter = MagicMock()
    with patch.dict(
        "services.llm.gateway._REGISTRY",
        {"anthropic": lambda model, **kw: fake_adapter},
    ):
        adapter = get_llm("anthropic", "claude-3-haiku", bypass_circuit=True)

    assert adapter is not None, (
        "bypass_circuit=True must return an adapter even when the circuit is open "
        "(used by check_provider_health() probes to detect recovery)."
    )


# ---------------------------------------------------------------------------
# CB-7: check_provider_health bypasses the circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_provider_health_bypasses_circuit() -> None:
    """CB-7 — check_provider_health() can still reach an unhealthy provider.

    If the circuit check were applied to health probes, they could never detect
    that a provider has recovered, trapping the circuit permanently open.
    """
    from services.llm.provider_status import (
        _UNHEALTHY_FAILURE_THRESHOLD,
        check_provider_health,
        record_provider_failure,
    )

    exc = RuntimeError("provider down")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD):
        record_provider_failure("anthropic", exc)

    # Mock the underlying adapter so no real HTTP call is made.
    fake_adapter = MagicMock()
    fake_adapter.complete = MagicMock(return_value="OK")

    async def _fake_complete(*args, **kwargs):
        return "OK"

    fake_adapter.complete = _fake_complete

    with (
        patch(
            "services.llm.gateway._REGISTRY",
            {"anthropic": lambda model, **kw: fake_adapter},
        ),
        patch(
            "services.llm.provider_config.JUDGE_MODELS", {"anthropic": "claude-3-haiku"}
        ),
        patch(
            "services.llm.provider_config.PROVIDER_DISPLAY", {"anthropic": "Anthropic"}
        ),
        patch("services.llm.provider_status.is_provider_configured", return_value=True),
        patch(
            "services.llm.provider_status.provider_snapshot",
            return_value={"id": "anthropic"},
        ),
    ):
        # Must not raise HTTPException(503) even though circuit is open.
        result = await check_provider_health("anthropic")

    # The health check itself should complete without raising 503.
    assert result is not None, (
        "check_provider_health() must not raise 503 even when the circuit is open — "
        "health probes must bypass the circuit to detect recovery."
    )


# ---------------------------------------------------------------------------
# CB-8: circuit window expiry
# ---------------------------------------------------------------------------


def test_can_route_true_after_window_expires() -> None:
    """CB-8 — failures older than _RECENT_FAILURE_WINDOW_SECONDS are ignored."""
    from services.llm import provider_status
    from services.llm.provider_status import (
        _RECENT_FAILURE_WINDOW_SECONDS,
        _UNHEALTHY_FAILURE_THRESHOLD,
        can_route,
    )

    exc = RuntimeError("old error")
    for _ in range(_UNHEALTHY_FAILURE_THRESHOLD):
        provider_status.record_provider_failure("google", exc)

    # Backdate the last_failure_at so the window has expired.
    state = provider_status._FAILURES["google"]
    state.last_failure_at = time.time() - _RECENT_FAILURE_WINDOW_SECONDS - 1

    assert can_route("google") is True, (
        "can_route must return True when the last failure is older than the "
        f"failure window ({_RECENT_FAILURE_WINDOW_SECONDS}s) — stale failures "
        "should not keep the circuit open."
    )

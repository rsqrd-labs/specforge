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
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

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

    assert adapter is fake_adapter, (
        "bypass_circuit=True must return the adapter even when the circuit is open "
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


# ---------------------------------------------------------------------------
# T-217 (C-1): generate() TimeoutError path must call record_provider_failure
# ---------------------------------------------------------------------------

# Shared helper to build the minimal mocks that get generate() past all
# pre-flight checks and into the adapter streaming step.  Both T-217 tests
# use this to avoid duplicating 30+ lines of mock setup.


def _make_generate_mocks(provider: str = "anthropic"):
    """Return a dict of patch targets → mock return values for generate()."""
    fake_stage = MagicMock()
    fake_stage.status = "draft"
    fake_stage.type = "spec"
    fake_stage.workspace_id = UUID("00000000-0000-0000-0000-000000000001")
    fake_stage.id = UUID("00000000-0000-0000-0000-000000000002")
    fake_stage.current_version = 0
    fake_stage.deduction_ledger_id = None

    fake_workspace = MagicMock()
    fake_workspace.problem_statement = "Build a simple TODO app"
    fake_workspace.id = UUID("00000000-0000-0000-0000-000000000001")
    # Attributes accessed by prompt builders / cache-key builder
    fake_workspace.spec_content = None
    fake_workspace.plan_content = None
    fake_workspace.harness_content = None

    fake_user = MagicMock()
    fake_user.id = UUID("00000000-0000-0000-0000-000000000003")
    fake_user.credit_balance = 100

    fake_deduction = MagicMock()
    fake_deduction.id = UUID("00000000-0000-0000-0000-000000000004")

    fake_route = MagicMock()
    fake_route.provider = provider
    fake_route.model = "claude-3-haiku"
    fake_route.model_tier = "fast"
    fake_route.operation = "spec.generate"  # must match OUTPUT_TOKEN_BUDGETS key
    fake_route.cross_provider_fallback = False

    fake_redis = AsyncMock()
    fake_db = AsyncMock()

    return {
        "fake_stage": fake_stage,
        "fake_workspace": fake_workspace,
        "fake_user": fake_user,
        "fake_deduction": fake_deduction,
        "fake_route": fake_route,
        "fake_redis": fake_redis,
        "fake_db": fake_db,
    }


async def _drain_generate(stage_manager, stage_id, user, db):
    """Drain the generate() async generator, returning the raised exception."""
    raised = None
    try:
        async for _ in stage_manager.generate(stage_id, user, db):
            pass
    except Exception as exc:
        raised = exc
    return raised


@pytest.mark.asyncio
async def test_generate_stream_timeout_records_provider_failure() -> None:
    """T-217 — generate() TimeoutError path must call record_provider_failure.

    asyncio.timeout() fires via CancelledError (BaseException), which bypasses
    InstrumentedAdapter.stream()'s `except Exception` guard entirely.  The
    outer `except (ProviderError, TimeoutError)` block in generate() is the
    only location that can record this failure.  Without the fix from T-217,
    three consecutive stream timeouts would never trip the circuit breaker.

    This test verifies the runtime behaviour: when a TimeoutError propagates
    to generate()'s except block, record_provider_failure is called exactly
    once with the correct provider.  C-1 — T-217.
    """
    from services.llm.base import ProviderTimeoutError
    from services.pipeline.stage_manager import stage_manager

    mocks = _make_generate_mocks(provider="anthropic")
    provider = "anthropic"

    # Adapter whose stream() raises TimeoutError, simulating asyncio.timeout()
    # firing when the provider hangs.
    async def _timeout_stream(*args, **kwargs):
        raise TimeoutError("stream timed out after 360s")
        yield  # pragma: no cover — make it an AsyncGenerator

    fake_adapter = MagicMock()
    fake_adapter.stream = _timeout_stream

    scan_result = MagicMock()
    scan_result.is_safe = True

    mock_credit = MagicMock()
    mock_credit.deduct = AsyncMock(return_value=mocks["fake_deduction"])
    mock_credit.refund = AsyncMock()
    mock_credit.invalidate = AsyncMock()  # T-219: post-commit cache eviction.

    with (
        patch.object(
            stage_manager, "_load_stage", AsyncMock(return_value=mocks["fake_stage"])
        ),
        patch.object(
            stage_manager,
            "_load_workspace",
            AsyncMock(return_value=mocks["fake_workspace"]),
        ),
        patch.object(stage_manager, "_assert_dependencies_finalised", AsyncMock()),
        patch("services.pipeline.stage_manager.assert_valid_problem_statement"),
        patch("services.pipeline.stage_manager.scan", return_value=scan_result),
        patch.object(
            stage_manager, "_redis_client", AsyncMock(return_value=mocks["fake_redis"])
        ),
        patch(
            "services.pipeline.stage_manager.sliding_window_check",
            AsyncMock(return_value=True),
        ),
        patch("services.pipeline.stage_manager._assert_visible_credit_balance"),
        patch(
            "services.pipeline.stage_manager._resolve_preflight_route",
            return_value=mocks["fake_route"],
        ),
        patch(
            "services.pipeline.stage_manager.build_prompt",
            AsyncMock(return_value=("system_prompt", "user_prompt")),
        ),
        patch(
            "services.pipeline.stage_manager.build_generation_cache_key",
            return_value="cache_key",
        ),
        patch(
            "services.pipeline.stage_manager.get_cached_generation",
            AsyncMock(return_value=None),
        ),
        patch("services.pipeline.stage_manager.credit_service", mock_credit),
        patch("services.pipeline.stage_manager.get_llm", return_value=fake_adapter),
        patch("services.llm.provider_status.record_provider_failure") as mock_rpf,
    ):
        exc = await _drain_generate(
            stage_manager,
            UUID("00000000-0000-0000-0000-000000000002"),
            mocks["fake_user"],
            mocks["fake_db"],
        )

    # generate() wraps TimeoutError into ProviderTimeoutError before re-raising.
    assert isinstance(
        exc, ProviderTimeoutError
    ), f"Expected ProviderTimeoutError from generate() on timeout path, got {exc!r}"

    # The critical assertion: record_provider_failure must be called exactly once.
    mock_rpf.assert_called_once()
    call_args = mock_rpf.call_args[0]
    assert call_args[0] == provider, (
        f"record_provider_failure must be called with provider={provider!r}, "
        f"got {call_args[0]!r}.  C-1 — T-217."
    )
    assert isinstance(call_args[1], TimeoutError), (
        f"record_provider_failure must receive the TimeoutError exc, "
        f"got {type(call_args[1])!r}.  C-1 — T-217."
    )


@pytest.mark.asyncio
async def test_generate_provider_error_does_not_double_count_record_provider_failure() -> (  # noqa: E501
    None
):
    """T-217 — generate() must NOT call record_provider_failure for ProviderError.

    Background: InstrumentedAdapter.stream() calls record_provider_failure in
    its `except Exception` block for non-timeout ProviderErrors (e.g. HTTP 401).
    An unconditional call in generate()'s except block would double-count those
    errors, tripping the circuit after 2 failures instead of the documented 3.

    This test verifies the isinstance(exc, TimeoutError) guard prevents the
    double-count: when a ProviderError propagates from the adapter, generate()'s
    except block does NOT call record_provider_failure (the call is left
    exclusively to InstrumentedAdapter.stream()'s except Exception handler).

    Without trace_id there is no InstrumentedAdapter wrapper, so the mock sees
    zero total calls — proving generate()'s own guard fires correctly.
    C-1 — T-217.
    """
    from services.llm.base import ProviderError
    from services.pipeline.stage_manager import stage_manager

    mocks = _make_generate_mocks(provider="anthropic")

    # Adapter whose stream() raises ProviderError directly (e.g., HTTP 401).
    async def _provider_error_stream(*args, **kwargs):
        raise ProviderError("anthropic", RuntimeError("401 Unauthorized"))
        yield  # pragma: no cover

    fake_adapter = MagicMock()
    fake_adapter.stream = _provider_error_stream

    scan_result = MagicMock()
    scan_result.is_safe = True

    mock_credit = MagicMock()
    mock_credit.deduct = AsyncMock(return_value=mocks["fake_deduction"])
    mock_credit.refund = AsyncMock()
    mock_credit.invalidate = AsyncMock()  # T-219: post-commit cache eviction.

    with (
        patch.object(
            stage_manager, "_load_stage", AsyncMock(return_value=mocks["fake_stage"])
        ),
        patch.object(
            stage_manager,
            "_load_workspace",
            AsyncMock(return_value=mocks["fake_workspace"]),
        ),
        patch.object(stage_manager, "_assert_dependencies_finalised", AsyncMock()),
        patch("services.pipeline.stage_manager.assert_valid_problem_statement"),
        patch("services.pipeline.stage_manager.scan", return_value=scan_result),
        patch.object(
            stage_manager, "_redis_client", AsyncMock(return_value=mocks["fake_redis"])
        ),
        patch(
            "services.pipeline.stage_manager.sliding_window_check",
            AsyncMock(return_value=True),
        ),
        patch("services.pipeline.stage_manager._assert_visible_credit_balance"),
        patch(
            "services.pipeline.stage_manager._resolve_preflight_route",
            return_value=mocks["fake_route"],
        ),
        patch(
            "services.pipeline.stage_manager.build_prompt",
            AsyncMock(return_value=("system_prompt", "user_prompt")),
        ),
        patch(
            "services.pipeline.stage_manager.build_generation_cache_key",
            return_value="cache_key",
        ),
        patch(
            "services.pipeline.stage_manager.get_cached_generation",
            AsyncMock(return_value=None),
        ),
        patch("services.pipeline.stage_manager.credit_service", mock_credit),
        patch("services.pipeline.stage_manager.get_llm", return_value=fake_adapter),
        patch("services.llm.provider_status.record_provider_failure") as mock_rpf,
    ):
        exc = await _drain_generate(
            stage_manager,
            UUID("00000000-0000-0000-0000-000000000002"),
            mocks["fake_user"],
            mocks["fake_db"],
        )

    # generate() re-raises ProviderError unchanged (no wrapping for non-timeout).
    assert isinstance(
        exc, ProviderError
    ), f"Expected ProviderError from generate() on provider error path, got {exc!r}"

    # The critical assertion: generate()'s except block must NOT call
    # record_provider_failure for ProviderError (the isinstance guard prevents it).
    # InstrumentedAdapter.stream() would call it once if it were wrapping; since
    # trace_id=None here there is no wrapper — and generate() itself must not add
    # a call, confirming zero double-counting.  C-1 — T-217.
    mock_rpf.assert_not_called(), (
        "generate()'s except block must NOT call record_provider_failure for "
        "ProviderError.  The isinstance(exc, TimeoutError) guard must prevent "
        "the call.  Without this guard, non-timeout ProviderErrors (already "
        "counted by InstrumentedAdapter) would be double-counted, tripping the "
        "circuit after 2 failures instead of 3.  C-1 — T-217."
    )

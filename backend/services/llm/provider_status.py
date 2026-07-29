"""Provider health tracking: circuit-breaker state and health-check probes.

This module contains no direct LLM HTTP calls.  HTTP timeout policy
(H-6 — T-182): timeout= enforcement is delegated to each adapter's httpx.Timeout.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

from prometheus_client import Counter, Gauge

from config import settings
from services.llm.provider_config import JUDGE_MODELS, PROVIDER_DISPLAY
from services.observability import (
    record_llm_provider_configured,
    record_llm_provider_failure,
    record_llm_provider_health,
)

ProviderHealth = Literal["not_configured", "healthy", "degraded", "unhealthy"]

_PROVIDER_KEY_SETTINGS = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "google": "google_api_key",
}
_PLACEHOLDER_PREFIXES = ("placeholder-",)
_RECENT_FAILURE_WINDOW_SECONDS = 600
_UNHEALTHY_FAILURE_THRESHOLD = 3

# _FAILURES is a module-level dict — its state is per-worker-process.
# Multi-worker deployments (e.g. Gunicorn with multiple uvicorn workers) will
# have independent circuit state per process: a provider can be open in one
# worker and healthy in another.  This is an accepted trade-off for simplicity;
# a distributed circuit would require a shared Redis counter.  LF-1 — T-197.
_FAILURES: dict[str, "ProviderFailureState"] = {}

# Prometheus counter for circuit-breaker activations.  Allows operators to
# detect and alert on unexpected or sustained circuit trips via dashboards.
# T-215 / CF-2 — T-197.
CIRCUIT_REJECTIONS = Counter(
    "thought2build_llm_circuit_rejections_total",
    "Number of requests rejected because the LLM provider circuit is open",
    ["provider"],
)

# Provider rate-limit / overload responses (HTTP 429/529/503). Distinct from a
# circuit failure: a rate-limit is throughput backpressure, not an outage, so it
# is counted here but deliberately NOT folded into the circuit-breaker failure
# count (audit F2 — otherwise the in-place backoff retry would hit an open
# circuit). A rising rate is the signal the shared provider key is at its ceiling.
PROVIDER_RATE_LIMITED = Counter(
    "thought2build_llm_provider_rate_limited_total",
    "LLM provider responses that throttled or overloaded the call (HTTP 429/529/503)",
    ["provider"],
)

# Gauge for current circuit breaker state per provider.  0 = closed (healthy),
# 1 = open (rejecting requests).  Updated synchronously in record_provider_failure()
# and record_provider_success().  Per-process; under multi-worker deployment,
# use max(thought2build_llm_circuit_state) by provider in Grafana.  M-2 — T-220.
CIRCUIT_STATE = Gauge(
    "thought2build_llm_circuit_state",
    "Current circuit breaker state per LLM provider (0=closed, 1=open)",
    ["provider"],
)


@dataclass
class ProviderFailureState:
    count: int = 0
    last_failure_at: float = 0
    last_error: str = ""


def provider_ids() -> tuple[str, ...]:
    return tuple(PROVIDER_DISPLAY)


def provider_api_key(provider: str) -> str:
    setting_name = _PROVIDER_KEY_SETTINGS[provider]
    return str(getattr(settings, setting_name))


def is_provider_configured(provider: str) -> bool:
    value = provider_api_key(provider).strip()
    configured = bool(value) and not value.lower().startswith(_PLACEHOLDER_PREFIXES)
    record_llm_provider_configured(provider, configured)
    return configured


def provider_snapshot(provider: str) -> dict[str, object]:
    configured = is_provider_configured(provider)
    status, message = _provider_health(provider, configured)
    record_llm_provider_health(provider, status)
    return {
        "id": provider,
        "name": PROVIDER_DISPLAY[provider],
        "configured": configured,
        "selectable": configured and status != "unhealthy",
        "health": status,
        "message": message,
    }


def all_provider_snapshots() -> list[dict[str, object]]:
    return [provider_snapshot(provider) for provider in provider_ids()]


def _circuit_open(provider: str) -> bool:
    """Return True if the provider circuit has tripped (≥ failure threshold).

    Reads _FAILURES directly rather than calling _provider_health() to avoid
    the configured/unconfigured ambiguity — a not-configured provider has no
    _FAILURES entry and is therefore not circuit-open.  CF-2 — T-197.
    """
    state = _FAILURES.get(provider)
    if state is None:
        return False
    if time.time() - state.last_failure_at > _RECENT_FAILURE_WINDOW_SECONDS:
        _FAILURES.pop(provider, None)
        return False
    return state.count >= _UNHEALTHY_FAILURE_THRESHOLD


def can_route(provider: str) -> bool:
    """Return False when the provider circuit is open; True otherwise.

    Called by gateway.get_llm() before returning an adapter to enforce the
    circuit breaker.  A False result causes get_llm() to raise
    HTTPException(503) and increment thought2build_llm_circuit_rejections_total
    so that operators can detect circuit activations in dashboards.

    NOTE: _FAILURES is per-worker-process.  In multi-worker deployments each
    process tracks failures independently — see the _FAILURES comment above.
    CF-2 — T-197.
    """
    return not _circuit_open(provider)


async def check_provider_health(
    provider: str,
    model: str | None = None,
) -> dict[str, object]:
    """Probe a provider with a 1-token completion and record the outcome.

    ``model`` defaults to ``JUDGE_MODELS[provider]`` — passing None is
    byte-identical to the historical behaviour.  Supplying an explicit model
    matters because a provider key can authenticate while still being denied a
    specific model: Anthropic keys carry per-workspace model permissions, so a
    key that probes fine against the Haiku judge model can still be refused
    ``claude-opus-5``, the model full-artifact generation depends on.  The
    caller is responsible for validating the id against the catalog — an
    arbitrary caller-supplied string must never reach a provider.
    """
    if provider not in PROVIDER_DISPLAY:
        raise ValueError(f"Unknown provider: {provider!r}")
    if not is_provider_configured(provider):
        return provider_snapshot(provider)

    try:
        from services.llm.gateway import get_llm

        # bypass_circuit=True: health probes must always reach the provider,
        # even when its circuit is open.  Without this, a tripped circuit
        # would block health checks, preventing them from detecting recovery
        # and resetting the circuit via record_provider_success().  CF-2 — T-197.
        adapter = get_llm(
            provider,
            model or JUDGE_MODELS[provider],
            bypass_circuit=True,
        )
        await asyncio.wait_for(
            adapter.complete(
                "You are a provider health checker. Reply with OK.",
                "OK",
                max_tokens=1,
            ),
            timeout=10,
        )
    except Exception as exc:
        record_provider_failure(provider, exc)
    else:
        record_provider_success(provider)
    return provider_snapshot(provider)


def record_provider_success(provider: str) -> None:
    _FAILURES.pop(provider, None)
    CIRCUIT_STATE.labels(provider=provider).set(0)  # Circuit closed — M-2 — T-220.
    record_llm_provider_health(provider, "healthy")


def record_provider_failure(provider: str, exc: BaseException) -> None:
    # A rate-limit / overload (HTTP 429/529/503) is throughput backpressure, not
    # a provider outage: count it on its own meter but do NOT advance the circuit
    # failure count (audit F2). Folding 429s into the circuit would open it under
    # load and then HTTPException(503) the very backoff retry that honors
    # Retry-After — turning graceful in-place retry into a hard failure.
    from services.llm.base import ProviderRateLimitError  # noqa: PLC0415

    if isinstance(exc, ProviderRateLimitError):
        PROVIDER_RATE_LIMITED.labels(provider=provider).inc()
        record_llm_provider_failure(provider, exc.__class__.__name__)
        return

    state = _FAILURES.setdefault(provider, ProviderFailureState())
    state.count += 1
    state.last_failure_at = time.time()
    state.last_error = exc.__class__.__name__
    record_llm_provider_failure(provider, state.last_error)
    record_llm_provider_health(provider, _provider_health(provider, True)[0])
    # Update Gauge AFTER all _FAILURES mutations so it reflects the post-failure
    # state.  _circuit_open() re-reads _FAILURES to determine open/closed.
    # M-2 — T-220.
    CIRCUIT_STATE.labels(provider=provider).set(1 if _circuit_open(provider) else 0)


def _provider_health(
    provider: str,
    configured: bool,
) -> tuple[ProviderHealth, str]:
    if not configured:
        return "not_configured", "API key is not configured."

    state = _FAILURES.get(provider)
    if state is None:
        return "healthy", "No provider issues detected."

    if time.time() - state.last_failure_at > _RECENT_FAILURE_WINDOW_SECONDS:
        _FAILURES.pop(provider, None)
        return "healthy", "No recent provider issues detected."

    if state.count >= _UNHEALTHY_FAILURE_THRESHOLD:
        return "unhealthy", f"Recent provider failures: {state.last_error}."
    return "degraded", f"Recent provider warning: {state.last_error}."

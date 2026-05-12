from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

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
_FAILURES: dict[str, "ProviderFailureState"] = {}


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


async def check_provider_health(provider: str) -> dict[str, object]:
    if provider not in PROVIDER_DISPLAY:
        raise ValueError(f"Unknown provider: {provider!r}")
    if not is_provider_configured(provider):
        return provider_snapshot(provider)

    try:
        from services.llm.gateway import get_llm

        adapter = get_llm(provider, JUDGE_MODELS[provider])
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
    record_llm_provider_health(provider, "healthy")


def record_provider_failure(provider: str, exc: BaseException) -> None:
    state = _FAILURES.setdefault(provider, ProviderFailureState())
    state.count += 1
    state.last_failure_at = time.time()
    state.last_error = exc.__class__.__name__
    record_llm_provider_failure(provider, state.last_error)
    record_llm_provider_health(provider, _provider_health(provider, True)[0])


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

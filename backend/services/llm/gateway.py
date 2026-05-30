from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time as _time
from collections import OrderedDict
from typing import TYPE_CHECKING

from fastapi import HTTPException

from config import settings
from services.llm.provider_status import CIRCUIT_REJECTIONS, can_route

if TYPE_CHECKING:
    from services.llm.base import BaseLLMAdapter

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {}
_PROVIDER_KEY_SETTINGS = {
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "google": ("GOOGLE_API_KEY", "google_api_key"),
}
# Adapter instances are cached per provider, model, and API-key fingerprint.
# When a provider key changes in the process environment, the fingerprint changes
# and the next get_llm() call builds a fresh provider client automatically.
# The cache is bounded to _INSTANCE_CACHE_MAX entries with LRU eviction so that
# users with many custom API keys cannot grow the cache without bound.  T-191.
_INSTANCE_CACHE_MAX = 256
# Adapters older than this are evicted on cache hit and rebuilt fresh.
# Ensures stale httpx connection pools are recycled periodically.  L-1 — T-223.
_INSTANCE_CACHE_TTL_SECONDS: float = 3600.0
_INSTANCES: OrderedDict[
    tuple[str, str, str], tuple["BaseLLMAdapter", float]
] = OrderedDict()

# Hard wall-clock cap on any single non-streaming generation call routed
# through the gateway.  Prevents a hung provider from holding a credit
# reservation indefinitely even if the per-request httpx.Timeout is somehow
# bypassed (e.g. chunked-transfer never terminates).  H-6 — T-182.
_WALL_CLOCK_TIMEOUT = 360.0  # seconds


def _register(provider: str, cls: type) -> None:
    _REGISTRY[provider] = cls


def get_llm(
    provider: str,
    model: str,
    *,
    bypass_circuit: bool = False,
) -> "BaseLLMAdapter":
    """Return a cached adapter for *provider* / *model*.

    Raises HTTPException(503) when the provider circuit is open (≥ 3 recent
    consecutive failures) unless *bypass_circuit=True*.  Health-check probes
    must pass bypass_circuit=True so they can reach an unhealthy provider and
    record a success that resets the circuit.  CF-2 — T-197.

    The circuit state is per-worker-process; see the _FAILURES comment in
    provider_status.py for multi-worker implications.
    """
    if provider not in _REGISTRY:
        raise ValueError(f"Unknown LLM provider: {provider!r}")

    # Enforce the circuit breaker: reject requests to providers whose failure
    # count has tripped the threshold.  Choosing hard-reject (503) over silent
    # fallback so callers can retry against a different provider explicitly
    # rather than silently masking the outage.  CF-2 — T-197.
    #
    # Increment the Prometheus rejection counter before raising so that even
    # if the HTTPException is swallowed at a higher level, the metric reflects
    # the rejection.  Counter is labelled by provider so operators can isolate
    # which provider's circuit is open.  T-215.
    if not bypass_circuit and not can_route(provider):
        CIRCUIT_REJECTIONS.labels(provider=provider).inc()
        logger.warning(
            "llm.circuit_open",
            extra={"provider": provider, "model": model},
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"LLM provider '{provider}' is temporarily unavailable "
                "(circuit open — too many recent failures)."
            ),
        )

    api_key = _provider_api_key(provider)
    key = (provider, model, _secret_fingerprint(api_key))
    if key in _INSTANCES:
        adapter, created_at = _INSTANCES[key]
        if _time.monotonic() - created_at < _INSTANCE_CACHE_TTL_SECONDS:
            # Fresh — move to end (most-recently-used) for LRU ordering.
            _INSTANCES.move_to_end(key)
            return adapter
        # TTL expired — evict the stale adapter and rebuild below.
        del _INSTANCES[key]
    # Evict the least-recently-used entry when the cache is full.
    if len(_INSTANCES) >= _INSTANCE_CACHE_MAX:
        _INSTANCES.popitem(last=False)
    new_adapter = _REGISTRY[provider](model, api_key=api_key)
    _INSTANCES[key] = (new_adapter, _time.monotonic())
    return new_adapter


async def complete_with_timeout(
    provider: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    *,
    timeout: float = _WALL_CLOCK_TIMEOUT,
) -> str:
    """Run adapter.complete() under a hard wall-clock timeout via asyncio.wait_for.

    Callers that need streaming should apply asyncio.timeout() around the
    stream loop directly; this helper targets one-shot completion calls where
    the entire coroutine must finish within *timeout* seconds.  H-6 — T-182.
    """
    adapter = get_llm(provider, model)
    return await asyncio.wait_for(
        adapter.complete(system, user, max_tokens),
        timeout=timeout,
    )


# Platform-funded judge model provider used by the Phase 19 critic when the
# workspace provider has no configured judge model.  anthropic is the platform
# primary (its API key is the only non-optional provider key in config).
_DEFAULT_JUDGE_PROVIDER = "anthropic"


async def call_judge_model(
    *,
    system_prompt: str,
    user_prompt: str,
    provider: str | None = None,
    max_tokens: int = 2048,
    timeout: float | None = None,
) -> str:
    """Run a one-shot completion against the cheap judge model for *provider*.

    Used by the Phase 19 critic (services/pipeline/critic.py).  Routes through
    the circuit-aware get_llm() and a hard wall-clock timeout.  Falls back to
    the platform-default judge provider when *provider* has no configured judge
    model so the gate keeps working regardless of the workspace's primary
    provider.  T-247.
    """
    from services.llm.provider_config import JUDGE_MODELS  # noqa: PLC0415

    judge_provider = provider if provider in JUDGE_MODELS else _DEFAULT_JUDGE_PROVIDER
    model = JUDGE_MODELS[judge_provider]
    effective_timeout = (
        timeout if timeout is not None else float(settings.llm_complete_timeout_seconds)
    )
    return await complete_with_timeout(
        judge_provider,
        model,
        system_prompt,
        user_prompt,
        max_tokens,
        timeout=effective_timeout,
    )


def clear_llm_cache() -> None:
    _INSTANCES.clear()


def _provider_api_key(provider: str) -> str:
    env_name, setting_name = _PROVIDER_KEY_SETTINGS[provider]
    return os.getenv(env_name) or str(getattr(settings, setting_name))


def _secret_fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _load_adapters() -> None:
    from services.llm.anthropic_adapter import AnthropicAdapter
    from services.llm.google_adapter import GoogleAdapter
    from services.llm.openai_adapter import OpenAIAdapter

    _register("anthropic", AnthropicAdapter)
    _register("openai", OpenAIAdapter)
    _register("google", GoogleAdapter)


_load_adapters()

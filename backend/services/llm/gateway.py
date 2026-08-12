from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time as _time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException

from config import settings
from services.llm.provider_status import CIRCUIT_REJECTIONS, can_route

if TYPE_CHECKING:
    from services.llm.base import BaseLLMAdapter
    from services.llm.cost_ledger import LLMCostContext
    from services.llm.prompt_cache import PromptCachePolicy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {}
_PROVIDER_KEY_SETTINGS = {
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "google": ("GOOGLE_API_KEY", "google_api_key"),
    "openrouter": ("OPENROUTER_API_KEY", "openrouter_api_key"),
}
# Adapter instances are cached per provider, model, operation policy, and API-key
# fingerprint.
# When a provider key changes in the process environment, the fingerprint changes
# and the next get_llm() call builds a fresh provider client automatically.
# The cache is bounded to _INSTANCE_CACHE_MAX entries with LRU eviction so that
# users with many custom API keys cannot grow the cache without bound.  T-191.
_INSTANCE_CACHE_MAX = 256
# Adapters older than this are evicted on cache hit and rebuilt fresh.
# Ensures stale httpx connection pools are recycled periodically.  L-1 — T-223.
_INSTANCE_CACHE_TTL_SECONDS: float = 3600.0
_INSTANCES: OrderedDict[tuple[str, str, str, str], tuple["BaseLLMAdapter", float]] = (
    OrderedDict()
)

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
    operation: str | None = None,
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
    policy_key = operation or "catalog"
    key = (provider, model, policy_key, _secret_fingerprint(api_key))
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
    new_adapter = _REGISTRY[provider](model, api_key=api_key, operation=operation)
    _INSTANCES[key] = (new_adapter, _time.monotonic())
    return new_adapter


def get_instrumented_llm(
    provider: str,
    model: str,
    *,
    operation: str,
    stage_type: str = "-",
    action: str | None = None,
    model_tier: str = "unknown",
    prompt_version: str = "local",
    cache_hit: bool = False,
    batch: bool = False,
    cross_provider_fallback: bool = False,
    cost_context: "LLMCostContext | None" = None,
    span_id: str | None = None,
    trace_id: str | None = None,
) -> "BaseLLMAdapter":
    """A circuit-aware adapter wrapped in InstrumentedAdapter for cost capture.

    The single front door for call sites that previously used the raw adapter
    (storyboard, increment, clarifier, judge calls) so every LLM call lands in
    the Phase-0 cost ledger. ``cost_context`` carries the product-surface FK
    attribution without growing this signature per domain field.
    """
    from services.llm.instrumented_adapter import InstrumentedAdapter  # noqa: PLC0415

    return InstrumentedAdapter(
        get_llm(provider, model, operation=operation),
        span_id=span_id,
        trace_id=trace_id,
        provider=provider,
        model=model,
        stage_type=stage_type,
        action=action or operation,
        model_tier=model_tier,
        prompt_version=prompt_version,
        operation=operation,
        cache_hit=cache_hit,
        batch=batch,
        cross_provider_fallback=cross_provider_fallback,
        cost_context=cost_context,
    )


async def complete_with_timeout(
    provider: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    *,
    timeout: float = _WALL_CLOCK_TIMEOUT,
    operation: str | None = None,
    stage_type: str = "-",
    model_tier: str = "unknown",
    cost_context: "LLMCostContext | None" = None,
    cache_system: bool = False,
    cache_policy: "PromptCachePolicy | None" = None,
) -> str:
    """Run adapter.complete() under a hard wall-clock timeout via asyncio.wait_for.

    Callers that need streaming should apply asyncio.timeout() around the
    stream loop directly; this helper targets one-shot completion calls where
    the entire coroutine must finish within *timeout* seconds.  H-6 — T-182.

    When *operation* is supplied the call is wrapped in InstrumentedAdapter so
    it is recorded in the cost ledger; omitting it preserves the original raw
    behaviour for callers that record elsewhere.

    *cache_system* is forwarded to the adapter so callers in multi-round
    completion paths (chunked generation, storyboard repair) can hint that the
    system prompt is stable and should be cached by the provider.
    """
    if operation is not None:
        adapter: BaseLLMAdapter = get_instrumented_llm(
            provider,
            model,
            operation=operation,
            stage_type=stage_type,
            model_tier=model_tier,
            cost_context=cost_context,
        )
    else:
        adapter = get_llm(provider, model)
    kwargs = {"cache_system": cache_system}
    if cache_policy is not None:
        kwargs["cache_policy"] = cache_policy
    return await asyncio.wait_for(
        adapter.complete(system, user, max_tokens, **kwargs), timeout=timeout
    )


# Platform-funded judge model provider used by the Phase 19 critic when the
# workspace provider has no configured judge model.  anthropic is the platform
# primary (its API key is the only non-optional provider key in config).
_DEFAULT_JUDGE_PROVIDER = "anthropic"


@dataclass(frozen=True)
class JudgeCallResult:
    """A judge-model completion plus the provider's stop information.

    ``stopped_by_limit`` is the provider-reported "output hit max_tokens" fact
    (never a heuristic) so callers that feed the completion downstream — e.g.
    the Rung-2 problem compressor, whose output becomes the problem statement
    for all four stages — can detect a silent hard truncation (audit M11).
    """

    text: str
    stopped_by_limit: bool


async def call_judge_model_with_info(
    *,
    system_prompt: str,
    user_prompt: str,
    provider: str | None = None,
    max_tokens: int = 2048,
    timeout: float | None = None,
    operation: str = "judge.call",
    stage_type: str = "-",
    cost_context: "LLMCostContext | None" = None,
) -> JudgeCallResult:
    """``call_judge_model`` variant that also reports the stop reason.

    Same routing, instrumentation, and timeout semantics; the adapter is held
    locally so its ``last_completion`` can be read after the call.
    """
    from services.llm.provider_config import JUDGE_MODELS  # noqa: PLC0415

    judge_provider = provider if provider in JUDGE_MODELS else _DEFAULT_JUDGE_PROVIDER
    model = JUDGE_MODELS[judge_provider]
    effective_timeout = (
        timeout if timeout is not None else float(settings.llm_complete_timeout_seconds)
    )
    adapter = get_instrumented_llm(
        judge_provider,
        model,
        operation=operation,
        stage_type=stage_type,
        model_tier="small",
        cost_context=cost_context,
    )
    text = await asyncio.wait_for(
        adapter.complete(system_prompt, user_prompt, max_tokens),
        timeout=effective_timeout,
    )
    completion = getattr(adapter, "last_completion", None)
    return JudgeCallResult(
        text=text,
        stopped_by_limit=bool(getattr(completion, "stopped_by_limit", False)),
    )


async def call_judge_model(
    *,
    system_prompt: str,
    user_prompt: str,
    provider: str | None = None,
    max_tokens: int = 2048,
    timeout: float | None = None,
    operation: str = "judge.call",
    stage_type: str = "-",
    cost_context: "LLMCostContext | None" = None,
) -> str:
    """Run a one-shot completion against the cheap judge model for *provider*.

    Used by the Phase 19 critic (services/pipeline/critic.py).  Routes through
    the circuit-aware get_llm() and a hard wall-clock timeout.  Falls back to
    the platform-default judge provider when *provider* has no configured judge
    model so the gate keeps working regardless of the workspace's primary
    provider.  T-247.
    """
    result = await call_judge_model_with_info(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        provider=provider,
        max_tokens=max_tokens,
        timeout=timeout,
        operation=operation,
        stage_type=stage_type,
        cost_context=cost_context,
    )
    return result.text


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
    from services.llm.openrouter_adapter import OpenRouterAdapter

    _register("anthropic", AnthropicAdapter)
    _register("openai", OpenAIAdapter)
    _register("google", GoogleAdapter)
    _register("openrouter", OpenRouterAdapter)


_load_adapters()

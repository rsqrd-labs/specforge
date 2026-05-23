"""LLM routing logic: resolves provider, model, and tier for each operation.

This module contains no HTTP calls.  HTTP timeout policy (H-6 — T-182):
timeout= enforcement is delegated to each concrete adapter implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.llm.cost_registry import (
    GENERATION_OPERATIONS,
    MODEL_TIERS,
    PROVIDER_CAPABILITY_REGISTRY,
    get_model_cost,
    model_tier,
    models_for_tier,
)


class LLMRoutingError(ValueError):
    pass


@dataclass(frozen=True)
class LLMRoute:
    provider: str
    model: str
    model_tier: str
    operation: str
    latency_class: str
    cross_provider_fallback: bool
    reason: str


def resolve_llm_route(
    *,
    operation: str,
    preferred_provider: str,
    requested_tier: str,
    fallback_tier: str | None = None,
    latency_class: str,
    allow_cross_provider: bool = False,
    preferred_model: str | None = None,
) -> LLMRoute:
    _validate_operation(operation)
    _validate_provider(preferred_provider)
    _validate_tier(requested_tier)
    if fallback_tier is not None:
        _validate_tier(fallback_tier)

    if preferred_model:
        return LLMRoute(
            provider=preferred_provider,
            model=_require_model(preferred_provider, preferred_model),
            model_tier=model_tier(preferred_provider, preferred_model),
            operation=operation,
            latency_class=latency_class,
            cross_provider_fallback=False,
            reason="preferred_model",
        )

    same_provider_route = _route_for_provider(
        provider=preferred_provider,
        operation=operation,
        requested_tier=requested_tier,
        fallback_tier=fallback_tier,
        latency_class=latency_class,
    )
    if same_provider_route is not None:
        return same_provider_route

    if not allow_cross_provider:
        raise LLMRoutingError(
            "No same-provider LLM route is available for "
            f"operation={operation!r}, provider={preferred_provider!r}, "
            f"tier={requested_tier!r}."
        )

    for provider in sorted(PROVIDER_CAPABILITY_REGISTRY):
        if provider == preferred_provider:
            continue
        route = _route_for_provider(
            provider=provider,
            operation=operation,
            requested_tier=requested_tier,
            fallback_tier=fallback_tier,
            latency_class=latency_class,
            cross_provider_fallback=True,
        )
        if route is not None:
            return route

    raise LLMRoutingError(
        "No LLM route is available for "
        f"operation={operation!r}, tier={requested_tier!r}."
    )


def _route_for_provider(
    *,
    provider: str,
    operation: str,
    requested_tier: str,
    fallback_tier: str | None,
    latency_class: str,
    cross_provider_fallback: bool = False,
) -> LLMRoute | None:
    for tier, reason in (
        (requested_tier, "requested_tier"),
        (fallback_tier, "fallback_tier"),
    ):
        if tier is None:
            continue
        model = _cheapest_model_for_operation(provider, tier, operation)
        if model is not None:
            return LLMRoute(
                provider=provider,
                model=model,
                model_tier=tier,
                operation=operation,
                latency_class=latency_class,
                cross_provider_fallback=cross_provider_fallback,
                reason=reason,
            )
    return None


def _cheapest_model_for_operation(
    provider: str,
    tier: str,
    operation: str,
) -> str | None:
    candidates = []
    for model in models_for_tier(provider, tier):
        config = get_model_cost(provider, model)
        operations = set(config["recommended_operations"])
        if operation not in operations:
            continue
        cost = float(config["input_cost_per_million"]) + float(
            config["output_cost_per_million"]
        )
        candidates.append((cost, model))
    if not candidates:
        return None
    return min(candidates)[1]


def _require_model(provider: str, model: str) -> str:
    get_model_cost(provider, model)
    return model


def _validate_operation(operation: str) -> None:
    if operation not in GENERATION_OPERATIONS:
        raise LLMRoutingError(f"Unknown LLM operation: {operation!r}")


def _validate_provider(provider: str) -> None:
    if provider not in PROVIDER_CAPABILITY_REGISTRY:
        raise LLMRoutingError(f"Unknown LLM provider: {provider!r}")


def _validate_tier(tier: str) -> None:
    if tier not in MODEL_TIERS:
        raise LLMRoutingError(f"Unknown LLM model tier: {tier!r}")

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
    requested_tier: str
    fallback_tier: str | None
    selection_reason: str


def platform_provider_priority() -> tuple[str, ...]:
    """Return the validated, server-owned provider precedence."""
    from config import settings  # noqa: PLC0415

    return tuple(settings.llm_provider_priority.split(","))


def resolve_platform_route(
    *,
    operation: str,
    requested_tier: str,
    fallback_tier: str | None = None,
    latency_class: str,
    exclude_providers: frozenset[str] = frozenset(),
) -> LLMRoute:
    """Resolve a route without accepting a user/workspace provider preference.

    Providers are considered only when their platform credential is configured,
    their local circuit is routable, and their catalog supports the operation.
    Rejection reasons stay internal; callers expose only a neutral availability
    failure at the product boundary.
    """
    from services.llm.provider_status import (  # noqa: PLC0415
        can_route,
        is_provider_configured,
    )

    _validate_operation(operation)
    _validate_tier(requested_tier)
    if fallback_tier is not None:
        _validate_tier(fallback_tier)

    for provider in platform_provider_priority():
        if provider in exclude_providers:
            continue
        if not is_provider_configured(provider) or not can_route(provider):
            continue
        route = _route_for_provider(
            provider=provider,
            operation=operation,
            requested_tier=requested_tier,
            fallback_tier=fallback_tier,
            latency_class=latency_class,
        )
        if route is not None:
            return route
    raise LLMRoutingError("No platform LLM route is currently available.")


def resolve_platform_judge_route(*, operation: str, latency_class: str) -> LLMRoute:
    """Select a server-owned judge route for non-generation helper calls."""
    from services.llm.provider_config import JUDGE_MODELS  # noqa: PLC0415
    from services.llm.provider_status import (  # noqa: PLC0415
        can_route,
        is_provider_configured,
    )

    for provider in platform_provider_priority():
        model = JUDGE_MODELS.get(provider)
        if model and is_provider_configured(provider) and can_route(provider):
            return LLMRoute(
                provider=provider,
                model=model,
                model_tier=model_tier(provider, model),
                operation=operation,
                latency_class=latency_class,
                cross_provider_fallback=False,
                reason="platform_priority",
                requested_tier="small",
                fallback_tier=None,
                selection_reason="server_owned_judge",
            )
    raise LLMRoutingError("No platform judge route is currently available.")


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
        _validate_preferred_model_operation(
            preferred_provider,
            preferred_model,
            operation,
        )
        return LLMRoute(
            provider=preferred_provider,
            model=_require_model(preferred_provider, preferred_model),
            model_tier=model_tier(preferred_provider, preferred_model),
            operation=operation,
            latency_class=latency_class,
            cross_provider_fallback=False,
            reason="preferred_model",
            requested_tier=requested_tier,
            fallback_tier=fallback_tier,
            selection_reason="explicit_model",
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
        selected = _model_for_operation(provider, tier, operation)
        if selected is not None:
            model, selection_reason = selected
            return LLMRoute(
                provider=provider,
                model=model,
                model_tier=tier,
                operation=operation,
                latency_class=latency_class,
                cross_provider_fallback=cross_provider_fallback,
                reason=reason,
                requested_tier=requested_tier,
                fallback_tier=fallback_tier,
                selection_reason=selection_reason,
            )
    return None


def _model_for_operation(
    provider: str,
    tier: str,
    operation: str,
) -> tuple[str, str] | None:
    default_candidates = []
    active_candidates = []
    for model in models_for_tier(provider, tier):
        config = get_model_cost(provider, model)
        if config["status"] != "active":
            continue
        operations = set(config["recommended_operations"])
        if operation not in operations:
            continue
        sortable = (
            int(config["routing_priority"]),
            _estimated_model_cost(config),
            model,
        )
        active_candidates.append((*sortable, model))
        if operation in set(config["default_operations"]):
            default_candidates.append((*sortable, model))

    if default_candidates:
        return sorted(default_candidates)[0][-1], "active_default"
    if active_candidates:
        return sorted(active_candidates)[0][-1], "active_same_tier"
    return None


def _estimated_model_cost(config: dict) -> float:
    costs = (
        config["input_cost_per_million"],
        config["output_cost_per_million"],
    )
    if any(value is None for value in costs):
        return float("inf")
    return float(costs[0]) + float(costs[1])


def _validate_preferred_model_operation(
    provider: str,
    model: str,
    operation: str,
) -> None:
    config = get_model_cost(provider, model)
    if operation not in set(config["recommended_operations"]):
        raise LLMRoutingError(
            f"Model {provider}/{model} is not configured for operation {operation!r}."
        )


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

from __future__ import annotations

import pytest

from services.llm.routing import LLMRoutingError, resolve_llm_route


def test_prefers_explicit_workspace_model() -> None:
    route = resolve_llm_route(
        operation="spec.generate",
        preferred_provider="openai",
        preferred_model="gpt-4o-mini",
        requested_tier="strong",
        fallback_tier="mid",
        latency_class="interactive",
    )

    assert route.provider == "openai"
    assert route.model == "gpt-4o-mini"
    assert route.model_tier == "mini"
    assert route.cross_provider_fallback is False
    assert route.reason == "preferred_model"


def test_routes_to_cheapest_same_provider_model_for_tier_and_operation() -> None:
    route = resolve_llm_route(
        operation="tasks.generate",
        preferred_provider="google",
        requested_tier="mini",
        fallback_tier="small",
        latency_class="interactive",
    )

    assert route.provider == "google"
    assert route.model == "gemini-2.0-flash"
    assert route.model_tier == "mini"
    assert route.cross_provider_fallback is False


def test_fallback_tier_stays_within_provider() -> None:
    route = resolve_llm_route(
        operation="summary.create",
        preferred_provider="anthropic",
        requested_tier="mini",
        fallback_tier="small",
        latency_class="background",
    )

    assert route.provider == "anthropic"
    assert route.model == "claude-haiku-4-5-20251001"
    assert route.model_tier == "small"
    assert route.reason == "fallback_tier"


def test_cross_provider_fallback_is_rejected_by_default() -> None:
    with pytest.raises(LLMRoutingError):
        resolve_llm_route(
            operation="summary.create",
            preferred_provider="anthropic",
            requested_tier="mini",
            latency_class="background",
        )


def test_cross_provider_fallback_must_be_explicit() -> None:
    route = resolve_llm_route(
        operation="summary.create",
        preferred_provider="anthropic",
        requested_tier="mini",
        latency_class="background",
        allow_cross_provider=True,
    )

    assert route.provider in {"google", "openai"}
    assert route.model_tier == "mini"
    assert route.cross_provider_fallback is True


def test_invalid_provider_model_or_operation_raises() -> None:
    with pytest.raises(LLMRoutingError):
        resolve_llm_route(
            operation="unknown.generate",
            preferred_provider="openai",
            requested_tier="strong",
            latency_class="interactive",
        )

    with pytest.raises(LLMRoutingError):
        resolve_llm_route(
            operation="spec.generate",
            preferred_provider="missing",
            requested_tier="strong",
            latency_class="interactive",
        )

    with pytest.raises(ValueError):
        resolve_llm_route(
            operation="spec.generate",
            preferred_provider="openai",
            preferred_model="missing",
            requested_tier="strong",
            latency_class="interactive",
        )

from __future__ import annotations

import pytest

from services.llm.routing import LLMRoutingError, resolve_llm_route


def test_prefers_explicit_workspace_model() -> None:
    route = resolve_llm_route(
        operation="spec.generate",
        preferred_provider="openai",
        preferred_model="gpt-5.5",
        requested_tier="strong",
        fallback_tier="mid",
        latency_class="interactive",
    )

    assert route.provider == "openai"
    assert route.model == "gpt-5.5"
    assert route.model_tier == "strong"
    assert route.cross_provider_fallback is False
    assert route.reason == "preferred_model"
    assert route.selection_reason == "explicit_model"


def test_routes_to_active_operation_default_for_tier_and_operation() -> None:
    route = resolve_llm_route(
        operation="tasks.generate",
        preferred_provider="google",
        requested_tier="mid",
        fallback_tier="small",
        latency_class="interactive",
    )

    assert route.provider == "google"
    assert route.model == "gemini-3.5-flash"
    assert route.model_tier == "mid"
    assert route.cross_provider_fallback is False
    assert route.selection_reason == "active_default"


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


def test_preferred_model_must_support_operation() -> None:
    with pytest.raises(LLMRoutingError):
        resolve_llm_route(
            operation="spec.generate",
            preferred_provider="openai",
            # gpt-4o only recommends summary.create, so it cannot serve a
            # core-generation operation even when named explicitly.
            preferred_model="gpt-4o",
            requested_tier="strong",
            latency_class="interactive",
        )


@pytest.mark.parametrize(
    ("provider", "requested_tier", "expected"),
    [
        ("anthropic", "small", "claude-haiku-4-5-20251001"),
        ("openai", "mini", "gpt-5.4-mini"),
        ("google", "mid", "gemini-3.5-flash"),
    ],
)
def test_core_generation_routes_use_cheap_primary_defaults(
    provider: str,
    requested_tier: str,
    expected: str,
) -> None:
    for operation in (
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
    ):
        route = resolve_llm_route(
            operation=operation,
            preferred_provider=provider,
            requested_tier=requested_tier,
            latency_class="interactive",
        )

        assert route.model == expected
        assert route.selection_reason == "active_default"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("anthropic", "claude-sonnet-4-6"),
        ("openai", "gpt-5.4"),
    ],
)
def test_mid_tier_escalation_stays_eligible_for_core_generation(
    provider: str,
    expected: str,
) -> None:
    route = resolve_llm_route(
        operation="spec.generate",
        preferred_provider=provider,
        requested_tier="mid",
        latency_class="interactive",
    )

    # The mid model recommends core ops for the runtime escalation retry but is
    # no longer the primary default for them.
    assert route.model == expected
    assert route.model_tier == "mid"
    assert route.selection_reason == "active_same_tier"


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("anthropic", "claude-opus-4-8"),
        ("openai", "gpt-5.5"),
    ],
)
def test_strong_tier_escalation_stays_eligible_for_core_generation(
    provider: str,
    expected: str,
) -> None:
    route = resolve_llm_route(
        operation="spec.generate",
        preferred_provider=provider,
        requested_tier="strong",
        latency_class="interactive",
    )

    assert route.model == expected
    assert route.model_tier == "strong"
    assert route.selection_reason == "active_same_tier"


def test_google_has_no_strong_tier_escalation_model() -> None:
    with pytest.raises(LLMRoutingError):
        resolve_llm_route(
            operation="spec.generate",
            preferred_provider="google",
            requested_tier="strong",
            latency_class="interactive",
        )

from __future__ import annotations

import pytest

from services.llm.cost_registry import (
    MODEL_TIERS,
    PROVIDER_CAPABILITY_REGISTRY,
    get_model_cost,
    get_provider_capabilities,
    model_tier,
    models_for_tier,
)


def test_registry_covers_supported_providers() -> None:
    assert {"anthropic", "openai", "google"} <= set(PROVIDER_CAPABILITY_REGISTRY)


def test_registry_exposes_provider_capabilities_copy() -> None:
    capabilities = get_provider_capabilities("openai")
    capabilities["supports_streaming"] = False

    assert PROVIDER_CAPABILITY_REGISTRY["openai"]["supports_streaming"] is True


def test_model_tier_lookup_and_tier_filtering() -> None:
    assert model_tier("openai", "gpt-5.4-mini") == "mini"
    assert "gpt-5.4-mini" in models_for_tier("openai", "mini")


def test_model_cost_lookup_returns_copy() -> None:
    model_cost = get_model_cost("google", "gemini-3.5-flash")
    model_cost["tier"] = "strong"

    assert model_cost["tier"] == "strong"
    assert (
        PROVIDER_CAPABILITY_REGISTRY["google"]["models"]["gemini-3.5-flash"]["tier"]
        == "strong"
    )


def test_google_registry_excludes_shutdown_gemini_flash_model() -> None:
    google_models = PROVIDER_CAPABILITY_REGISTRY["google"]["models"]

    assert "gemini-2.0-flash" not in google_models
    assert "gemini-3.5-flash" in google_models
    assert google_models["gemini-1.5-flash"]["status"] == "deprecated"


def test_registry_exposes_model_policy_fields() -> None:
    model_config = get_model_cost("openai", "gpt-5.5")

    assert model_config["status"] == "active"
    assert model_config["adapter_api"] == "responses"
    assert model_config["supports_reasoning"] is True
    assert model_config["default_operations"] == [
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
        "regenerate.full",
    ]


def test_required_tiers_are_present() -> None:
    tiers = {
        config["tier"]
        for provider in PROVIDER_CAPABILITY_REGISTRY.values()
        for config in provider["models"].values()
    }

    assert {"strong", "mid", "mini", "small"} <= tiers
    assert {"strong", "mid", "mini", "small"} <= MODEL_TIERS


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("missing", "gpt-4o"),
        ("openai", "missing"),
    ],
)
def test_unknown_provider_or_model_raises(provider: str, model: str) -> None:
    with pytest.raises(ValueError):
        get_model_cost(provider, model)

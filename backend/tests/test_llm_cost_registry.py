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
    model_cost = get_model_cost("google", "gemini-3.6-flash")
    model_cost["tier"] = "strong"

    assert model_cost["tier"] == "strong"
    assert (
        PROVIDER_CAPABILITY_REGISTRY["google"]["models"]["gemini-3.6-flash"]["tier"]
        == "mid"
    )


def test_google_registry_excludes_shutdown_gemini_flash_model() -> None:
    google_models = PROVIDER_CAPABILITY_REGISTRY["google"]["models"]

    assert "gemini-2.0-flash" not in google_models
    assert "gemini-3.6-flash" in google_models
    assert google_models["gemini-3.6-flash"]["status"] == "active"
    assert google_models["gemini-1.5-flash"]["status"] == "deprecated"
    # Superseded by the 3.6 Flash / 3.5 Flash-Lite cutover: retained for
    # historical row resolution, but demoted so they can never route again.
    assert google_models["gemini-3.5-flash"]["status"] == "deprecated"
    assert google_models["gemini-3.1-flash-lite"]["status"] == "deprecated"


def test_live_google_models_are_priceable() -> None:
    """Google is the platform provider, so every live Google model must carry
    real per-token rates.

    ``usage.estimate_cost_usd`` returns None the moment any needed rate is None,
    which silently records a zero-cost ledger row. The superseded 3.1 Flash-Lite
    entry had None for all three rates — harmless while Google was unconfigured,
    wrong now that Flash-Lite owns the entire judge/eval path.
    """
    google_models = PROVIDER_CAPABILITY_REGISTRY["google"]["models"]

    for model_id in ("gemini-3.6-flash", "gemini-3.5-flash-lite"):
        config = google_models[model_id]
        for field in (
            "input_cost_per_million",
            "cached_input_cost_per_million",
            "output_cost_per_million",
        ):
            assert config[field] is not None, f"{model_id}.{field} must be priced"
            assert config[field] > 0


def test_registry_exposes_model_policy_fields() -> None:
    model_config = get_model_cost("openai", "gpt-5.4")

    assert model_config["status"] == "active"
    assert model_config["adapter_api"] == "responses"
    assert model_config["supports_reasoning"] is True
    # gpt-5.4 is the mid-tier for core gen (Phase 1, issue #26) and section
    # refinement; both appear in default_operations.
    assert set(model_config["default_operations"]) >= {
        "refine.section",
        "storyboard.generate",
    }


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

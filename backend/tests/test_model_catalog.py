from __future__ import annotations

import pytest

from services.llm import model_catalog as catalog_module
from services.llm.model_catalog import (
    CORE_GENERATION_OPERATIONS,
    CORE_GENERATION_TIER_LADDER,
    MODEL_CATALOG,
    REQUIRED_PROVIDERS,
    core_generation_ladder,
    core_generation_tier_policy,
    default_model_for_operation,
    model_entry,
    model_request_policy,
    validate_core_generation_ladder,
    validate_model_catalog,
)


def test_catalog_validates_at_startup() -> None:
    validate_model_catalog()


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-5.4-mini"),
        ("google", "gemini-3.5-flash"),
    ],
)
def test_core_generation_defaults_are_cheap_primary_models(
    provider: str,
    expected_model: str,
) -> None:
    for operation in CORE_GENERATION_OPERATIONS:
        assert default_model_for_operation(provider, operation) == expected_model


def test_no_deprecated_model_is_an_active_default() -> None:
    deprecated_ids = {
        "claude-opus-4-7",
        "gpt-4o",
        "gpt-4o-mini",
        "o1-preview",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    }

    for entry in MODEL_CATALOG:
        if entry.model_id in deprecated_ids:
            assert entry.status == "deprecated"
            assert entry.default_operations == ()


def test_preview_gemini_models_are_cataloged_but_not_production_defaults() -> None:
    for model_id in ("gemini-3.1-pro-preview", "gemini-3-flash-preview"):
        entry = model_entry("google", model_id)

        assert entry.status == "preview"
        assert entry.default_operations == ()


# --- Phase 5b: core-generation tier ladder -----------------------------------


def test_every_required_provider_declares_a_ladder() -> None:
    assert set(CORE_GENERATION_TIER_LADDER) == set(REQUIRED_PROVIDERS)


def test_derived_policy_is_byte_identical_to_shipped_cheap_primary() -> None:
    # Phase 5b is a *behavior-preserving* normalization: deriving the live
    # cheap-primary policy from the catalog ladder must reproduce exactly what
    # Phase 5 shipped as a hand-maintained dict. If this changes, a model
    # actually runs differently and the Phase-5 golden-corpus gate is required.
    assert core_generation_tier_policy("anthropic") == ("small", "mid")
    assert core_generation_tier_policy("openai") == ("mini", "mid")
    assert core_generation_tier_policy("google") == ("mid", "strong")


def test_stage_manager_policy_derives_from_catalog_ladder() -> None:
    from services.pipeline import stage_manager

    for provider in REQUIRED_PROVIDERS:
        assert stage_manager.CORE_GENERATION_TIER_POLICY[provider] == (
            core_generation_tier_policy(provider)
        )


def test_google_floor_stays_mid_flash_lite_is_not_a_core_gen_default() -> None:
    # Flash-Lite (small) exists and is active, but is deliberately NOT a core-gen
    # default — Google's documented floor is mid (Flash). Lowering it is a routing
    # change gated by the Phase-5 live eval, not a Phase-5b edit.
    assert core_generation_ladder("google")[0] == "mid"
    flash_lite = model_entry("google", "gemini-3.1-flash-lite")
    assert flash_lite.tier == "small"
    assert not any(
        op in flash_lite.default_operations for op in CORE_GENERATION_OPERATIONS
    )


def test_ladders_are_strictly_increasing_in_capability() -> None:
    rank = catalog_module._CORE_TIER_RANK
    for provider, ladder in CORE_GENERATION_TIER_LADDER.items():
        ranks = [rank[tier] for tier in ladder]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(ranks), f"{provider} ladder not strict: {ladder}"


def test_each_primary_tier_resolves_to_exactly_one_active_default() -> None:
    for provider in REQUIRED_PROVIDERS:
        primary_tier = core_generation_ladder(provider)[0]
        actives = [
            entry
            for entry in MODEL_CATALOG
            if entry.provider == provider
            and entry.tier == primary_tier
            and entry.status == "active"
            and any(op in entry.default_operations for op in CORE_GENERATION_OPERATIONS)
        ]
        assert len(actives) == 1, (provider, primary_tier, actives)


def test_ladder_validator_rejects_non_increasing_ladder(monkeypatch) -> None:
    monkeypatch.setitem(CORE_GENERATION_TIER_LADDER, "anthropic", ("mid", "small"))
    with pytest.raises(RuntimeError, match="strictly"):
        validate_core_generation_ladder()


def test_ladder_validator_rejects_unknown_tier(monkeypatch) -> None:
    monkeypatch.setitem(CORE_GENERATION_TIER_LADDER, "openai", ("judge", "mid"))
    with pytest.raises(RuntimeError, match="non-core tier"):
        validate_core_generation_ladder()


def test_ladder_validator_rejects_too_short_ladder(monkeypatch) -> None:
    monkeypatch.setitem(CORE_GENERATION_TIER_LADDER, "google", ("mid",))
    with pytest.raises(RuntimeError, match="primary, fallback"):
        validate_core_generation_ladder()


def test_frontier_adapter_policy_is_explicit() -> None:
    assert model_request_policy("openai", "gpt-5.5") == {
        "adapter_api": "responses",
        "supports_reasoning": True,
        "supports_thinking": False,
        "reasoning_effort": "high",
        "thinking_level": None,
        "automatic_prompt_caching": True,
        "prompt_cache_key": True,
        "extended_prompt_cache_retention": True,
        "cached_token_accounting": True,
        "minimum_cacheable_input_tokens": 1024,
    }
    assert (
        model_request_policy("google", "gemini-3.5-flash")["thinking_level"] == "high"
    )
    assert (
        model_request_policy("anthropic", "claude-opus-4-8")["reasoning_effort"]
        == "high"
    )


def test_core_generation_low_reasoning_is_flagged_and_operation_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "core_generation_low_reasoning", True)

    assert (
        model_request_policy(
            "anthropic",
            "claude-haiku-4-5-20251001",
            "spec.generate",
        )["reasoning_effort"]
        == "low"
    )
    assert (
        model_request_policy("openai", "gpt-5.4-mini", "tasks.generate")[
            "reasoning_effort"
        ]
        == "low"
    )
    assert (
        model_request_policy("google", "gemini-3.5-flash", "harness.generate")[
            "thinking_level"
        ]
        == "low"
    )

    # The same cheap primary models keep their catalog policy outside core stage
    # generation, preventing judge/eval/refine/storyboard policy leakage.
    assert (
        model_request_policy(
            "anthropic",
            "claude-haiku-4-5-20251001",
            "refine.focused",
        )["reasoning_effort"]
        == "medium"
    )
    assert (
        model_request_policy("openai", "gpt-5.4-mini", "eval.score")["reasoning_effort"]
        == "medium"
    )
    assert (
        model_request_policy("google", "gemini-3.5-flash", "storyboard.generate")[
            "thinking_level"
        ]
        == "high"
    )


def test_core_generation_low_reasoning_flag_off_preserves_catalog_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "core_generation_low_reasoning", False)

    assert (
        model_request_policy(
            "anthropic",
            "claude-haiku-4-5-20251001",
            "plan.generate",
        )["reasoning_effort"]
        == "medium"
    )
    assert (
        model_request_policy("openai", "gpt-5.4-mini", "tasks.generate")[
            "reasoning_effort"
        ]
        == "medium"
    )
    assert (
        model_request_policy("google", "gemini-3.5-flash", "spec.generate")[
            "thinking_level"
        ]
        == "high"
    )

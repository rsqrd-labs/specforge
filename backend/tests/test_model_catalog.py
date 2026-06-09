from __future__ import annotations

import pytest

from services.llm.model_catalog import (
    CORE_GENERATION_OPERATIONS,
    MODEL_CATALOG,
    default_model_for_operation,
    model_entry,
    model_request_policy,
    validate_model_catalog,
)


def test_catalog_validates_at_startup() -> None:
    validate_model_catalog()


@pytest.mark.parametrize(
    ("provider", "expected_model"),
    [
        ("anthropic", "claude-opus-4-8"),
        ("openai", "gpt-5.5"),
        ("google", "gemini-3.5-flash"),
    ],
)
def test_core_generation_defaults_are_frontier_models(
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


def test_frontier_adapter_policy_is_explicit() -> None:
    assert model_request_policy("openai", "gpt-5.5") == {
        "adapter_api": "responses",
        "supports_reasoning": True,
        "supports_thinking": False,
        "reasoning_effort": "high",
        "thinking_level": None,
    }
    assert (
        model_request_policy("google", "gemini-3.5-flash")["thinking_level"] == "high"
    )
    assert (
        model_request_policy("anthropic", "claude-opus-4-8")["reasoning_effort"]
        == "high"
    )

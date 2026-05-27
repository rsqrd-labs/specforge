"""Provider capability registry and per-model cost configuration.

This module contains no HTTP calls.  HTTP timeout policy (H-6 — T-182):
timeout= enforcement is delegated to each concrete adapter implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

REQUIRED_PROVIDERS = frozenset({"anthropic", "openai", "google"})
MODEL_TIERS = frozenset({"strong", "mid", "mini", "small", "judge", "embedding"})
REQUIRED_PROVIDER_CAPABILITIES = frozenset(
    {
        "supports_streaming",
        "supports_prompt_cache_accounting",
        "supports_batch",
        "supports_usage_tokens",
    }
)
REQUIRED_MODEL_FIELDS = frozenset(
    {
        "tier",
        "input_cost_per_million",
        "cached_input_cost_per_million",
        "output_cost_per_million",
        "max_context_tokens",
        "default_max_output_tokens",
        "recommended_operations",
    }
)

GENERATION_OPERATIONS = frozenset(
    {
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
        "refine.focused",
        "refine.section",
        "regenerate.full",
        "summary.create",
        "eval.score",
    }
)


PROVIDER_CAPABILITY_REGISTRY: dict[str, dict[str, Any]] = {
    "anthropic": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
        "models": {
            "claude-opus-4-7": {
                "tier": "strong",
                "input_cost_per_million": 5.0,
                "cached_input_cost_per_million": 0.5,
                "output_cost_per_million": 25.0,
                "max_context_tokens": 200_000,
                "default_max_output_tokens": 8192,
                "recommended_operations": [
                    "spec.generate",
                    "plan.generate",
                    "harness.generate",
                    "regenerate.full",
                ],
            },
            "claude-sonnet-4-6": {
                "tier": "mid",
                "input_cost_per_million": 3.0,
                "cached_input_cost_per_million": 0.3,
                "output_cost_per_million": 15.0,
                "max_context_tokens": 200_000,
                "default_max_output_tokens": 8192,
                "recommended_operations": [
                    "plan.generate",
                    "harness.generate",
                    "refine.section",
                ],
            },
            "claude-haiku-4-5-20251001": {
                "tier": "small",
                "input_cost_per_million": 1.0,
                "cached_input_cost_per_million": 0.1,
                "output_cost_per_million": 5.0,
                "max_context_tokens": 200_000,
                "default_max_output_tokens": 4096,
                "recommended_operations": [
                    "tasks.generate",
                    "refine.focused",
                    "summary.create",
                    "eval.score",
                ],
            },
        },
    },
    "openai": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
        "models": {
            "gpt-4o": {
                "tier": "strong",
                "input_cost_per_million": 2.5,
                "cached_input_cost_per_million": 1.25,
                "output_cost_per_million": 10.0,
                "max_context_tokens": 128_000,
                "default_max_output_tokens": 8192,
                "recommended_operations": [
                    "spec.generate",
                    "plan.generate",
                    "harness.generate",
                    "regenerate.full",
                ],
            },
            "gpt-4o-mini": {
                "tier": "mini",
                "input_cost_per_million": 0.15,
                "cached_input_cost_per_million": 0.075,
                "output_cost_per_million": 0.6,
                "max_context_tokens": 128_000,
                "default_max_output_tokens": 4096,
                "recommended_operations": [
                    "harness.generate",
                    "tasks.generate",
                    "refine.focused",
                    "summary.create",
                    "eval.score",
                ],
            },
            "o1-preview": {
                "tier": "strong",
                "input_cost_per_million": 15.0,
                "cached_input_cost_per_million": 7.5,
                "output_cost_per_million": 60.0,
                "max_context_tokens": 128_000,
                "default_max_output_tokens": 8192,
                "recommended_operations": [
                    "spec.generate",
                    "plan.generate",
                    "regenerate.full",
                ],
            },
        },
    },
    "google": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
        "models": {
            "gemini-1.5-pro": {
                "tier": "strong",
                "input_cost_per_million": 1.25,
                "cached_input_cost_per_million": 0.125,
                "output_cost_per_million": 5.0,
                "max_context_tokens": 1_000_000,
                "default_max_output_tokens": 8192,
                "recommended_operations": [
                    "spec.generate",
                    "plan.generate",
                    "harness.generate",
                    "regenerate.full",
                ],
            },
            "gemini-1.5-flash": {
                "tier": "small",
                "input_cost_per_million": 0.075,
                "cached_input_cost_per_million": 0.01875,
                "output_cost_per_million": 0.3,
                "max_context_tokens": 1_000_000,
                "default_max_output_tokens": 4096,
                "recommended_operations": [
                    "tasks.generate",
                    "refine.focused",
                    "summary.create",
                    "eval.score",
                ],
            },
            "gemini-3.5-flash": {
                "tier": "mini",
                "input_cost_per_million": 1.5,
                "cached_input_cost_per_million": 0.15,
                "output_cost_per_million": 9.0,
                "max_context_tokens": 1_048_576,
                "default_max_output_tokens": 8192,
                "recommended_operations": [
                    "harness.generate",
                    "tasks.generate",
                    "refine.focused",
                    "refine.section",
                    "summary.create",
                ],
            },
        },
    },
}


def get_provider_capabilities(provider: str) -> dict[str, Any]:
    _require_provider(provider)
    return deepcopy(PROVIDER_CAPABILITY_REGISTRY[provider])


def get_model_cost(provider: str, model: str) -> dict[str, Any]:
    model_config = _model_config(provider, model)
    return deepcopy(model_config)


def models_for_tier(provider: str, tier: str) -> list[str]:
    _require_provider(provider)
    if tier not in MODEL_TIERS:
        raise ValueError(f"Unknown model tier: {tier!r}")

    models = PROVIDER_CAPABILITY_REGISTRY[provider]["models"]
    return [
        model
        for model, config in models.items()
        if config["tier"] == tier
    ]


def model_tier(provider: str, model: str) -> str:
    return str(_model_config(provider, model)["tier"])


def _model_config(provider: str, model: str) -> dict[str, Any]:
    _require_provider(provider)
    models = PROVIDER_CAPABILITY_REGISTRY[provider]["models"]
    if model not in models:
        raise ValueError(f"Unknown model for provider {provider!r}: {model!r}")
    return models[model]


def _require_provider(provider: str) -> None:
    if provider not in PROVIDER_CAPABILITY_REGISTRY:
        raise ValueError(f"Unknown LLM provider: {provider!r}")


def _validate_registry() -> None:
    missing_providers = REQUIRED_PROVIDERS - set(PROVIDER_CAPABILITY_REGISTRY)
    if missing_providers:
        raise RuntimeError(
            "Provider capability registry missing providers: "
            f"{sorted(missing_providers)}"
        )

    observed_tiers: set[str] = set()
    for provider, config in PROVIDER_CAPABILITY_REGISTRY.items():
        _validate_provider(provider, config)
        for model, model_config in config["models"].items():
            _validate_model(provider, model, model_config)
            observed_tiers.add(model_config["tier"])

    missing_tiers = {"strong", "mid", "mini", "small"} - observed_tiers
    if missing_tiers:
        raise RuntimeError(
            "Provider capability registry missing model tiers: "
            f"{sorted(missing_tiers)}"
        )


def _validate_provider(provider: str, config: dict[str, Any]) -> None:
    missing = REQUIRED_PROVIDER_CAPABILITIES - set(config)
    if missing:
        raise RuntimeError(
            f"{provider} registry entry missing capabilities: {sorted(missing)}"
        )
    if not isinstance(config.get("models"), dict) or not config["models"]:
        raise RuntimeError(f"{provider} registry entry must define models")


def _validate_model(provider: str, model: str, config: dict[str, Any]) -> None:
    missing = REQUIRED_MODEL_FIELDS - set(config)
    if missing:
        raise RuntimeError(
            f"{provider}/{model} missing cost-routing fields: {sorted(missing)}"
        )

    tier = config["tier"]
    if tier not in MODEL_TIERS:
        raise RuntimeError(f"{provider}/{model} has invalid tier: {tier!r}")

    for field in (
        "input_cost_per_million",
        "cached_input_cost_per_million",
        "output_cost_per_million",
    ):
        value = config[field]
        if value is not None and value < 0:
            raise RuntimeError(f"{provider}/{model} has negative {field}")

    for field in ("max_context_tokens", "default_max_output_tokens"):
        if not isinstance(config[field], int) or config[field] <= 0:
            raise RuntimeError(f"{provider}/{model} has invalid {field}")

    operations = config["recommended_operations"]
    if not _is_nonempty_string_iterable(operations):
        raise RuntimeError(f"{provider}/{model} must recommend operations")

    invalid_operations = set(operations) - GENERATION_OPERATIONS
    if invalid_operations:
        raise RuntimeError(
            f"{provider}/{model} has invalid recommended operations: "
            f"{sorted(invalid_operations)}"
        )


def _is_nonempty_string_iterable(value: object) -> bool:
    return (
        isinstance(value, Iterable)
        and not isinstance(value, str | bytes)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
    )


_validate_registry()

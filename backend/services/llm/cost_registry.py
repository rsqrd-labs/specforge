"""Provider capability registry and per-model cost configuration.

This module contains no HTTP calls.  HTTP timeout policy (H-6 — T-182):
timeout= enforcement is delegated to each concrete adapter implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from services.llm.model_catalog import (
    GENERATION_OPERATIONS,
    MODEL_TIERS,
    REQUIRED_PROVIDERS,
    build_provider_capability_registry,
)

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
        "default_operations",
        "display_name",
        "status",
        "adapter_api",
        "supports_reasoning",
        "supports_thinking",
        "rollout_notes",
        "routing_priority",
    }
)

PROVIDER_CAPABILITY_REGISTRY: dict[str, dict[str, Any]] = (
    build_provider_capability_registry()
)


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
    return [model for model, config in models.items() if config["tier"] == tier]


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

    default_operations = config["default_operations"]
    if not isinstance(default_operations, Iterable) or isinstance(
        default_operations, str | bytes
    ):
        raise RuntimeError(f"{provider}/{model} has invalid default_operations")

    invalid_defaults = set(default_operations) - set(operations)
    if invalid_defaults:
        raise RuntimeError(
            f"{provider}/{model} has default operations that are not recommended: "
            f"{sorted(invalid_defaults)}"
        )

    status = config["status"]
    if status not in {"active", "preview", "deprecated"}:
        raise RuntimeError(f"{provider}/{model} has invalid status: {status!r}")
    if status in {"preview", "deprecated"} and default_operations:
        raise RuntimeError(
            f"{provider}/{model} cannot be a production default with status {status!r}"
        )

    adapter_api = config["adapter_api"]
    supported_adapter_apis = {
        "anthropic": {"messages"},
        "openai": {"responses", "chat_completions"},
        "google": {"generate_content"},
    }[provider]
    if adapter_api not in supported_adapter_apis:
        raise RuntimeError(
            f"{provider}/{model} uses unsupported adapter API: {adapter_api!r}"
        )

    if not isinstance(config["supports_reasoning"], bool):
        raise RuntimeError(f"{provider}/{model} has invalid supports_reasoning")
    if not isinstance(config["supports_thinking"], bool):
        raise RuntimeError(f"{provider}/{model} has invalid supports_thinking")
    if not isinstance(config["rollout_notes"], str) or not config["rollout_notes"]:
        raise RuntimeError(f"{provider}/{model} must define rollout_notes")
    if not isinstance(config["routing_priority"], int):
        raise RuntimeError(f"{provider}/{model} has invalid routing_priority")


def _is_nonempty_string_iterable(value: object) -> bool:
    return (
        isinstance(value, Iterable)
        and not isinstance(value, str | bytes)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
    )


_validate_registry()

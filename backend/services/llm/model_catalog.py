"""Canonical LLM model catalog and routing policy.

This module is the single source of truth for provider model IDs, active
defaults, adapter API shape, and production rollout status. Provider-facing
catalogs and cost registries derive from this data so future model swaps are
made in one controlled place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ProviderId = Literal["anthropic", "openai", "google"]
ModelTier = Literal["strong", "mid", "mini", "small", "judge", "embedding"]
ModelStatus = Literal["active", "preview", "deprecated"]
AdapterApi = Literal["messages", "responses", "chat_completions", "generate_content"]

REQUIRED_PROVIDERS = frozenset({"anthropic", "openai", "google"})
MODEL_TIERS = frozenset({"strong", "mid", "mini", "small", "judge", "embedding"})
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
CORE_GENERATION_OPERATIONS = (
    "spec.generate",
    "plan.generate",
    "harness.generate",
    "tasks.generate",
    "regenerate.full",
)

PROVIDER_CAPABILITIES: dict[str, dict[str, bool]] = {
    "anthropic": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
    },
    "openai": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
    },
    "google": {
        "supports_streaming": True,
        "supports_prompt_cache_accounting": True,
        "supports_batch": True,
        "supports_usage_tokens": True,
    },
}


@dataclass(frozen=True)
class ModelCatalogEntry:
    provider: ProviderId
    model_id: str
    display_name: str
    tier: ModelTier
    status: ModelStatus
    adapter_api: AdapterApi
    input_cost_per_million: float | None
    cached_input_cost_per_million: float | None
    output_cost_per_million: float | None
    max_context_tokens: int
    default_max_output_tokens: int
    recommended_operations: tuple[str, ...]
    default_operations: tuple[str, ...]
    supports_reasoning: bool = False
    supports_thinking: bool = False
    reasoning_effort: str | None = None
    thinking_level: str | None = None
    rollout_notes: str = ""
    routing_priority: int = 100

    def to_registry_config(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "tier": self.tier,
            "status": self.status,
            "adapter_api": self.adapter_api,
            "input_cost_per_million": self.input_cost_per_million,
            "cached_input_cost_per_million": self.cached_input_cost_per_million,
            "output_cost_per_million": self.output_cost_per_million,
            "max_context_tokens": self.max_context_tokens,
            "default_max_output_tokens": self.default_max_output_tokens,
            "recommended_operations": list(self.recommended_operations),
            "default_operations": list(self.default_operations),
            "supports_reasoning": self.supports_reasoning,
            "supports_thinking": self.supports_thinking,
            "reasoning_effort": self.reasoning_effort,
            "thinking_level": self.thinking_level,
            "rollout_notes": self.rollout_notes,
            "routing_priority": self.routing_priority,
        }


MODEL_CATALOG: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        tier="strong",
        status="active",
        adapter_api="messages",
        input_cost_per_million=5.0,
        cached_input_cost_per_million=0.5,
        output_cost_per_million=25.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=32768,
        # Core generation ops are RECOMMENDED (not default) so the frontier
        # tier is never the primary route but stays eligible as the runtime
        # escalation when a mid-tier generation times out or errors.
        recommended_operations=CORE_GENERATION_OPERATIONS,
        default_operations=(),
        supports_reasoning=True,
        reasoning_effort="high",
        rollout_notes=(
            "Anthropic frontier escalation tier for core ASDD generation "
            "(one-shot runtime retry after a mid-tier failure)."
        ),
        routing_priority=1,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        tier="mid",
        status="active",
        adapter_api="messages",
        input_cost_per_million=3.0,
        cached_input_cost_per_million=0.3,
        output_cost_per_million=15.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=32768,
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "refine.section"),
        default_operations=("refine.section",),
        supports_reasoning=True,
        reasoning_effort="medium",
        rollout_notes=(
            "Anthropic mid-tier core ASDD generation escalation (one-shot retry "
            "after a Haiku 4.5 failure) and section refinement default."
        ),
        routing_priority=20,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        tier="small",
        status="active",
        adapter_api="messages",
        input_cost_per_million=1.0,
        cached_input_cost_per_million=0.1,
        output_cost_per_million=5.0,
        max_context_tokens=200_000,
        # Raised from 4096 so the cheap primary can carry the full core-gen
        # output budget (24576) without the model ceiling truncating artifacts.
        default_max_output_tokens=32768,
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "summary.create",
            "eval.score",
        ),
        default_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "summary.create",
            "eval.score",
        ),
        supports_reasoning=True,
        # Medium (not low) effort: as the core-gen primary, Haiku must reason
        # hard enough to clear the completeness/critic gates.  Per-model field,
        # so this also lifts its judge/eval/focused-refine uses to medium.
        reasoning_effort="medium",
        rollout_notes=(
            "Primary Anthropic core ASDD generation default — cheapest viable "
            "current-generation model — plus lightweight judge and focused refine."
        ),
        routing_priority=30,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-opus-4-7",
        display_name="Claude Opus 4.7",
        tier="strong",
        status="deprecated",
        adapter_api="messages",
        input_cost_per_million=5.0,
        cached_input_cost_per_million=0.5,
        output_cost_per_million=25.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-5.5",
        display_name="GPT-5.5",
        tier="strong",
        status="active",
        adapter_api="responses",
        input_cost_per_million=5.0,
        cached_input_cost_per_million=0.5,
        output_cost_per_million=30.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=32768,
        # Core generation ops are RECOMMENDED (not default) so the frontier
        # tier is never the primary route but stays eligible as the runtime
        # escalation when a mid-tier generation times out or errors.
        recommended_operations=CORE_GENERATION_OPERATIONS,
        default_operations=(),
        supports_reasoning=True,
        reasoning_effort="high",
        rollout_notes=(
            "OpenAI frontier escalation tier for core ASDD generation "
            "(one-shot runtime retry after a mid-tier failure)."
        ),
        routing_priority=1,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-5.4",
        display_name="GPT-5.4",
        tier="mid",
        status="active",
        adapter_api="responses",
        input_cost_per_million=2.5,
        cached_input_cost_per_million=0.25,
        output_cost_per_million=15.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=32768,
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "refine.section"),
        default_operations=("refine.section",),
        supports_reasoning=True,
        reasoning_effort="medium",
        rollout_notes=(
            "OpenAI mid-tier core ASDD generation escalation (one-shot retry "
            "after a GPT-5.4 Mini failure) and section refinement default."
        ),
        routing_priority=20,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-5.4-mini",
        display_name="GPT-5.4 Mini",
        tier="mini",
        status="active",
        adapter_api="responses",
        input_cost_per_million=0.75,
        cached_input_cost_per_million=0.075,
        output_cost_per_million=4.5,
        max_context_tokens=400_000,
        # Raised from 4096 so the cheap primary can carry the full core-gen
        # output budget (24576) without the model ceiling truncating artifacts.
        default_max_output_tokens=32768,
        recommended_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "refine.section",
            "summary.create",
            "eval.score",
        ),
        default_operations=(
            *CORE_GENERATION_OPERATIONS,
            "refine.focused",
            "summary.create",
            "eval.score",
        ),
        supports_reasoning=True,
        # Medium (not low) effort: as the core-gen primary, Mini must reason
        # hard enough to clear the completeness/critic gates.  Per-model field,
        # so this also lifts its judge/eval/non-core uses to medium.
        reasoning_effort="medium",
        rollout_notes=(
            "Primary OpenAI core ASDD generation default — cheapest viable "
            "current-generation model — plus lightweight non-core operations."
        ),
        routing_priority=30,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-4o",
        display_name="GPT-4o",
        tier="strong",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=2.5,
        cached_input_cost_per_million=1.25,
        output_cost_per_million=10.0,
        max_context_tokens=128_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-4o-mini",
        display_name="GPT-4o Mini",
        tier="mini",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=0.15,
        cached_input_cost_per_million=0.075,
        output_cost_per_million=0.6,
        max_context_tokens=128_000,
        default_max_output_tokens=4096,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="o1-preview",
        display_name="o1 Preview",
        tier="strong",
        status="deprecated",
        adapter_api="chat_completions",
        input_cost_per_million=15.0,
        cached_input_cost_per_million=7.5,
        output_cost_per_million=60.0,
        max_context_tokens=128_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash",
        # Flash is Google's fast/cheap core-generation model, so it sits on
        # the mid tier — the primary core-generation route. Google has no
        # active strong-tier escalation model; a runtime failure surfaces
        # directly instead of retrying on a second model.
        tier="mid",
        status="active",
        adapter_api="generate_content",
        input_cost_per_million=1.5,
        cached_input_cost_per_million=0.15,
        output_cost_per_million=9.0,
        max_context_tokens=1_048_576,
        default_max_output_tokens=32768,
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "refine.section"),
        default_operations=(*CORE_GENERATION_OPERATIONS, "refine.section"),
        supports_thinking=True,
        thinking_level="high",
        rollout_notes="Stable Gemini 3-family core ASDD generation default.",
        routing_priority=1,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash-Lite",
        tier="small",
        status="active",
        adapter_api="generate_content",
        input_cost_per_million=None,
        cached_input_cost_per_million=None,
        output_cost_per_million=None,
        max_context_tokens=1_048_576,
        default_max_output_tokens=4096,
        recommended_operations=("refine.focused", "summary.create", "eval.score"),
        default_operations=("refine.focused", "summary.create", "eval.score"),
        supports_thinking=True,
        thinking_level="low",
        rollout_notes="Stable Gemini 3-family lightweight routing and judge model.",
        routing_priority=30,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3.1-pro-preview",
        display_name="Gemini 3.1 Pro Preview",
        tier="strong",
        status="preview",
        adapter_api="generate_content",
        input_cost_per_million=None,
        cached_input_cost_per_million=None,
        output_cost_per_million=None,
        max_context_tokens=1_048_576,
        default_max_output_tokens=8192,
        recommended_operations=CORE_GENERATION_OPERATIONS,
        default_operations=(),
        supports_thinking=True,
        thinking_level="high",
        rollout_notes="Preview only; not a production default without eval evidence.",
        routing_priority=50,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-3-flash-preview",
        display_name="Gemini 3 Flash Preview",
        tier="mid",
        status="preview",
        adapter_api="generate_content",
        input_cost_per_million=None,
        cached_input_cost_per_million=None,
        output_cost_per_million=None,
        max_context_tokens=1_048_576,
        default_max_output_tokens=8192,
        recommended_operations=(*CORE_GENERATION_OPERATIONS, "refine.section"),
        default_operations=(),
        supports_thinking=True,
        thinking_level="high",
        rollout_notes="Preview only; not a production default without eval evidence.",
        routing_priority=60,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-1.5-pro",
        display_name="Gemini 1.5 Pro",
        tier="strong",
        status="deprecated",
        adapter_api="generate_content",
        input_cost_per_million=1.25,
        cached_input_cost_per_million=0.125,
        output_cost_per_million=5.0,
        max_context_tokens=1_000_000,
        default_max_output_tokens=8192,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
    ModelCatalogEntry(
        provider="google",
        model_id="gemini-1.5-flash",
        display_name="Gemini 1.5 Flash",
        tier="small",
        status="deprecated",
        adapter_api="generate_content",
        input_cost_per_million=0.075,
        cached_input_cost_per_million=0.01875,
        output_cost_per_million=0.3,
        max_context_tokens=1_000_000,
        default_max_output_tokens=4096,
        recommended_operations=("summary.create",),
        default_operations=(),
        rollout_notes="Deprecated legacy validation compatibility only.",
        routing_priority=500,
    ),
)


def iter_model_entries(provider: str | None = None) -> tuple[ModelCatalogEntry, ...]:
    if provider is None:
        return MODEL_CATALOG
    return tuple(entry for entry in MODEL_CATALOG if entry.provider == provider)


def model_entry(provider: str, model_id: str) -> ModelCatalogEntry:
    for entry in MODEL_CATALOG:
        if entry.provider == provider and entry.model_id == model_id:
            return entry
    raise ValueError(f"Unknown model for provider {provider!r}: {model_id!r}")


def valid_model_ids(provider: str) -> set[str]:
    _require_provider(provider)
    return {entry.model_id for entry in iter_model_entries(provider)}


def public_model_list(provider: str) -> list[dict[str, str]]:
    _require_provider(provider)
    return [
        {"id": entry.model_id, "name": entry.display_name}
        for entry in iter_model_entries(provider)
    ]


def default_model_for_operation(provider: str, operation: str) -> str:
    candidates = [
        entry
        for entry in iter_model_entries(provider)
        if entry.status == "active" and operation in entry.default_operations
    ]
    if not candidates:
        raise ValueError(
            "No active default model for "
            f"provider={provider!r}, operation={operation!r}"
        )
    return sorted(candidates, key=lambda entry: entry.routing_priority)[0].model_id


def build_provider_capability_registry() -> dict[str, dict[str, Any]]:
    validate_model_catalog()
    registry: dict[str, dict[str, Any]] = {}
    for provider, capabilities in PROVIDER_CAPABILITIES.items():
        registry[provider] = {**capabilities, "models": {}}
    for entry in MODEL_CATALOG:
        registry[entry.provider]["models"][entry.model_id] = entry.to_registry_config()
    return registry


def model_max_output_tokens(provider: str, model_id: str) -> int:
    """The hard per-call output-token ceiling for a catalog model.

    Used to clamp per-operation output budgets: reasoning tokens share this
    budget with visible artifact tokens on frontier models, so the ceiling
    must be generous enough that thinking never starves the artifact.
    """
    return model_entry(provider, model_id).default_max_output_tokens


def model_request_policy(provider: str, model_id: str) -> dict[str, str | None | bool]:
    entry = model_entry(provider, model_id)
    return {
        "adapter_api": entry.adapter_api,
        "supports_reasoning": entry.supports_reasoning,
        "supports_thinking": entry.supports_thinking,
        "reasoning_effort": entry.reasoning_effort,
        "thinking_level": entry.thinking_level,
    }


def validate_model_catalog() -> None:
    missing_providers = REQUIRED_PROVIDERS - set(PROVIDER_CAPABILITIES)
    if missing_providers:
        raise RuntimeError(
            f"Model catalog missing providers: {sorted(missing_providers)}"
        )

    seen_ids: set[str] = set()
    provider_operation_defaults: dict[tuple[str, str], list[str]] = {}
    for entry in MODEL_CATALOG:
        if entry.model_id in seen_ids:
            raise RuntimeError(f"Duplicate model catalog ID: {entry.model_id}")
        seen_ids.add(entry.model_id)
        _validate_entry(entry)
        if entry.status == "active":
            for operation in entry.default_operations:
                provider_operation_defaults.setdefault(
                    (entry.provider, operation), []
                ).append(entry.model_id)

    for provider in REQUIRED_PROVIDERS:
        for operation in CORE_GENERATION_OPERATIONS:
            defaults = provider_operation_defaults.get((provider, operation), [])
            if len(defaults) != 1:
                raise RuntimeError(
                    "Core generation operation must have exactly one active "
                    f"default: provider={provider!r}, operation={operation!r}, "
                    f"defaults={defaults!r}"
                )


def _validate_entry(entry: ModelCatalogEntry) -> None:
    _require_provider(entry.provider)
    if entry.tier not in MODEL_TIERS:
        raise RuntimeError(f"{entry.provider}/{entry.model_id} invalid tier")
    if entry.adapter_api not in _adapter_apis_for_provider(entry.provider):
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} uses unsupported adapter API "
            f"{entry.adapter_api!r}"
        )
    if entry.status == "deprecated" and entry.default_operations:
        raise RuntimeError(
            f"Deprecated model cannot be an active default: {entry.model_id}"
        )
    if not entry.recommended_operations:
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} must recommend operations"
        )
    invalid_operations = set(entry.recommended_operations) - GENERATION_OPERATIONS
    if invalid_operations:
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} invalid operations: "
            f"{sorted(invalid_operations)}"
        )
    invalid_defaults = set(entry.default_operations) - set(entry.recommended_operations)
    if invalid_defaults:
        raise RuntimeError(
            f"{entry.provider}/{entry.model_id} default operations are not "
            f"recommended: {sorted(invalid_defaults)}"
        )
    if entry.status == "preview" and entry.default_operations:
        raise RuntimeError(
            f"Preview model cannot be a production default: {entry.model_id}"
        )
    for field in ("max_context_tokens", "default_max_output_tokens"):
        if getattr(entry, field) <= 0:
            raise RuntimeError(f"{entry.provider}/{entry.model_id} invalid {field}")
    for field in (
        "input_cost_per_million",
        "cached_input_cost_per_million",
        "output_cost_per_million",
    ):
        value = getattr(entry, field)
        if value is not None and value < 0:
            raise RuntimeError(f"{entry.provider}/{entry.model_id} negative {field}")


def _adapter_apis_for_provider(provider: str) -> set[str]:
    return {
        "anthropic": {"messages"},
        "openai": {"responses", "chat_completions"},
        "google": {"generate_content"},
    }[provider]


def _require_provider(provider: str) -> None:
    if provider not in REQUIRED_PROVIDERS:
        raise ValueError(f"Unknown LLM provider: {provider!r}")


validate_model_catalog()

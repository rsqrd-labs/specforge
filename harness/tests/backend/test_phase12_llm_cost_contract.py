"""
Harness contracts for Plan v1.md §16, Phase 12 — provider-agnostic LLM API
cost optimization.

These tests intentionally describe the future implementation contract. They
are allowed to be RED before Phase 12 is implemented and GREEN after the LLM
gateway, routing, telemetry, and cache layers honor the plan.

Design invariants enforced here:
  * Cost optimization is provider agnostic: OpenAI, Anthropic, and Google are
    all represented through the same tier/capability abstraction.
  * Stage/pipeline logic asks for provider-neutral operations and model tiers;
    concrete model names stay in provider configuration.
  * Prompt reuse, batch execution, usage accounting, and cache behavior are
    capability-driven because providers expose different features.
  * Cross-provider fallback is never silent.
  * Every LLM call can emit a normalized cost event that is comparable across
    providers.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from conftest import BACKEND_ROOT, REPO_ROOT, import_backend, read_backend_file


REQUIRED_PROVIDERS = {"openai", "anthropic", "google"}
REQUIRED_TIERS = {"strong", "mid", "mini", "small"}
REQUIRED_MODEL_FIELDS = {
    "tier",
    "input_cost_per_million",
    "cached_input_cost_per_million",
    "output_cost_per_million",
    "max_context_tokens",
    "default_max_output_tokens",
    "recommended_operations",
}
REQUIRED_PROVIDER_CAPABILITIES = {
    "supports_streaming",
    "supports_prompt_cache_accounting",
    "supports_batch",
    "supports_usage_tokens",
}


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    assert isinstance(value, dict), f"{name} must be a dict, got {type(value)!r}"
    return value


def test_phase12_cost_event_schema_is_provider_normalized() -> None:
    """Plan §16.13: the harness must define a provider-normalized cost event
    schema that can compare OpenAI, Anthropic, and Google calls."""
    schema_path = REPO_ROOT / "harness" / "schemas" / "llm-cost-event.schema.json"
    assert schema_path.exists(), "Missing harness schema: llm-cost-event.schema.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = set(schema["required"])
    expected = {
        "workspace_id",
        "user_id",
        "stage_type",
        "operation",
        "provider",
        "model",
        "model_tier",
        "prompt_version",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "usage_estimation_method",
        "estimated_cost_usd",
        "latency_ms",
    }
    assert expected <= required

    provider_enum = set(schema["properties"]["provider"]["enum"])
    assert REQUIRED_PROVIDERS <= provider_enum

    tier_enum = set(schema["properties"]["model_tier"]["enum"])
    assert REQUIRED_TIERS <= tier_enum


def test_provider_capability_cost_registry_exists_for_all_llm_providers() -> None:
    """Plan §16.4: OpenAI, Anthropic, and Google must share one provider
    capability/cost registry instead of hard-coded cost logic per stage."""
    module = import_backend("services.llm.cost_registry")
    registry = _require_mapping(
        getattr(module, "PROVIDER_CAPABILITY_REGISTRY", None),
        "PROVIDER_CAPABILITY_REGISTRY",
    )

    missing_providers = REQUIRED_PROVIDERS - set(registry)
    assert not missing_providers, (
        "Provider capability registry must include all planned providers: "
        f"{sorted(missing_providers)}"
    )

    observed_tiers: set[str] = set()
    for provider in REQUIRED_PROVIDERS:
        provider_config = _require_mapping(registry[provider], f"{provider} config")
        missing_caps = REQUIRED_PROVIDER_CAPABILITIES - set(provider_config)
        assert not missing_caps, (
            f"{provider} registry entry is missing capabilities: {sorted(missing_caps)}"
        )

        models = _require_mapping(provider_config.get("models"), f"{provider}.models")
        assert models, f"{provider}.models must not be empty"

        for model_name, model_config in models.items():
            model_config = _require_mapping(
                model_config,
                f"{provider}.models.{model_name}",
            )
            missing_fields = REQUIRED_MODEL_FIELDS - set(model_config)
            assert not missing_fields, (
                f"{provider}/{model_name} is missing cost-routing fields: "
                f"{sorted(missing_fields)}"
            )
            assert model_config["tier"] in REQUIRED_TIERS | {"judge", "embedding"}
            observed_tiers.add(model_config["tier"])

    assert REQUIRED_TIERS <= observed_tiers, (
        "Registry must include at least one model for each provider-neutral tier: "
        f"{sorted(REQUIRED_TIERS - observed_tiers)}"
    )


def test_stage_logic_uses_provider_neutral_routing_not_model_names() -> None:
    """Plan §16.3-16.5: Stage Manager must request operations/tiers through a
    routing policy; it must not hard-code OpenAI, Anthropic, or Google model
    names in pipeline logic."""
    stage_manager_source = read_backend_file("services", "pipeline", "stage_manager.py")

    forbidden_model_fragments = [
        "gpt-",
        "o1-",
        "claude-",
        "gemini-",
    ]
    leaked = [
        fragment
        for fragment in forbidden_model_fragments
        if fragment in stage_manager_source.lower()
    ]
    assert not leaked, (
        "Stage Manager must not hard-code concrete provider model names. "
        f"Found fragments: {leaked}"
    )

    assert "resolve_llm_route" in stage_manager_source or "routing_policy" in stage_manager_source, (
        "Stage Manager should call a provider-neutral routing policy such as "
        "resolve_llm_route(...) before invoking get_llm()."
    )


def test_llm_routing_policy_requires_explicit_cross_provider_fallback() -> None:
    """Plan §16.5 and §16.15: cross-provider fallback must never silently send
    user content to a different vendor."""
    routing = import_backend("services.llm.routing")
    assert hasattr(routing, "resolve_llm_route"), (
        "services.llm.routing must expose resolve_llm_route()."
    )

    signature = inspect.signature(routing.resolve_llm_route)
    parameters = signature.parameters
    for expected in [
        "operation",
        "preferred_provider",
        "requested_tier",
        "fallback_tier",
        "latency_class",
    ]:
        assert expected in parameters, (
            f"resolve_llm_route() missing provider-neutral parameter: {expected}"
        )

    cross_provider_param = parameters.get("allow_cross_provider")
    assert cross_provider_param is not None, (
        "resolve_llm_route() must require allow_cross_provider so fallback is explicit."
    )
    assert cross_provider_param.default is False, (
        "allow_cross_provider must default to False. Cross-provider fallback may "
        "only happen by explicit operator policy."
    )


def test_generation_cache_key_includes_provider_model_tier_and_prompt_version() -> None:
    """Plan §16.11: cached outputs must never be replayed across providers,
    models, tiers, prompt versions, or upstream artifact hashes."""
    cache_module = import_backend("services.llm.cost_cache")
    assert hasattr(cache_module, "build_generation_cache_key"), (
        "services.llm.cost_cache must expose build_generation_cache_key()."
    )

    signature = inspect.signature(cache_module.build_generation_cache_key)
    expected_params = {
        "prompt_version",
        "stage_type",
        "operation",
        "provider",
        "model",
        "model_tier",
        "problem_statement_hash",
        "upstream_artifact_hashes",
        "user_instruction_hash",
        "output_contract_version",
    }
    missing = expected_params - set(signature.parameters)
    assert not missing, (
        "build_generation_cache_key() is missing cache isolation inputs: "
        f"{sorted(missing)}"
    )


def test_instrumented_adapter_records_provider_normalized_cost_metadata() -> None:
    """Plan §16.13: every instrumented LLM call must include provider, model,
    model_tier, prompt_version, token usage, estimation method, and cost fields."""
    source = read_backend_file("services", "llm", "instrumented_adapter.py")
    required_fragments = [
        "model_tier",
        "prompt_version",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "provider_usage_raw",
        "usage_estimation_method",
        "estimated_cost_usd",
        "cache_hit",
        "batch",
        "cross_provider_fallback",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in source]
    assert not missing, (
        "InstrumentedAdapter generation metadata is missing provider-normalized "
        f"cost fields: {missing}"
    )


def test_adapters_expose_or_normalize_usage_without_changing_base_interface() -> None:
    """Plan §16.13: provider usage accounting must be normalized without
    changing BaseLLMAdapter.stream(system, user, max_tokens) or complete(...)."""
    base = import_backend("services.llm.base")
    BaseLLMAdapter = base.BaseLLMAdapter

    stream_params = list(inspect.signature(BaseLLMAdapter.stream).parameters)
    complete_params = list(inspect.signature(BaseLLMAdapter.complete).parameters)
    assert stream_params == ["self", "system", "user", "max_tokens"]
    assert complete_params == ["self", "system", "user", "max_tokens"]

    usage_module = import_backend("services.llm.usage")
    for expected in [
        "normalize_provider_usage",
        "estimate_tokens",
        "estimate_cost_usd",
    ]:
        assert hasattr(usage_module, expected), (
            f"services.llm.usage must expose {expected}() for provider-agnostic "
            "cost telemetry."
        )


def test_prompt_builders_keep_static_moat_prefix_before_dynamic_context() -> None:
    """Plan §16.6: ASDD methodology, security rules, and output rules must stay
    in a stable static prefix before dynamic workspace context."""
    prompt_files = [
        BACKEND_ROOT / "prompts" / "spec.py",
        BACKEND_ROOT / "prompts" / "plan.py",
        BACKEND_ROOT / "prompts" / "harness.py",
        BACKEND_ROOT / "prompts" / "tasks.py",
    ]

    for prompt_path in prompt_files:
        source = prompt_path.read_text(encoding="utf-8")
        assert "ASDD_METHODOLOGY_OVERVIEW" in source, (
            f"{prompt_path.relative_to(REPO_ROOT)} must include the ASDD static prefix."
        )
        assert "SECURITY_AND_PRIVACY_RULES" in source, (
            f"{prompt_path.relative_to(REPO_ROOT)} must include security rules "
            "in the static prefix."
        )
        assert "PROFESSIONAL_OUTPUT_RULES" in source, (
            f"{prompt_path.relative_to(REPO_ROOT)} must include output rules "
            "in the static prefix."
        )
        system_index = source.index("SYSTEM_PROMPT")
        user_builder_index = source.index("build_user_prompt")
        assert system_index < user_builder_index, (
            f"{prompt_path.relative_to(REPO_ROOT)} must keep static system prompt "
            "construction before dynamic user prompt construction."
        )


def test_manifest_references_phase12_cost_contracts() -> None:
    """Plan §16.17: future TASKS entries must be able to reference the Phase 12
    cost-optimization harness group by manifest id."""
    manifest_path = REPO_ROOT / "harness" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = manifest.get("test_groups", [])
    matching = [
        group
        for group in groups
        if group.get("id") == "provider-agnostic-llm-cost-contracts"
    ]
    assert matching, (
        "harness/manifest.json must include a provider-agnostic LLM cost "
        "contract group for Phase 12."
    )
    assert matching[0]["path"] == "harness/tests/backend/test_phase12_llm_cost_contract.py"

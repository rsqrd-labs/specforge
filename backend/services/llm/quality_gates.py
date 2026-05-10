from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.llm.cost_registry import GENERATION_OPERATIONS, REQUIRED_PROVIDERS

PROMOTION_RULES = [
    "No deterministic validator regressions versus the baseline route.",
    "Average quality score must meet the operation/provider threshold.",
    "Human reviewer acceptance is required for sampled outputs.",
    "Estimated cost reduction must meet the operation target.",
    "Security coverage must not regress for regulated or adversarial prompts.",
]

ROUTE_QUALITY_GATES: dict[str, dict[str, Any]] = {
    "spec.generate": {
        "baseline_tier": "strong",
        "candidate_tiers": ["mid"],
        "min_average_quality_score": 0.92,
        "min_cost_reduction_ratio": 0.25,
        "requires_security_regression_review": True,
    },
    "plan.generate": {
        "baseline_tier": "strong",
        "candidate_tiers": ["mid"],
        "min_average_quality_score": 0.90,
        "min_cost_reduction_ratio": 0.25,
        "requires_security_regression_review": True,
    },
    "harness.generate": {
        "baseline_tier": "mid",
        "candidate_tiers": ["mini"],
        "min_average_quality_score": 0.88,
        "min_cost_reduction_ratio": 0.35,
        "requires_security_regression_review": True,
    },
    "tasks.generate": {
        "baseline_tier": "mid",
        "candidate_tiers": ["mini", "small"],
        "min_average_quality_score": 0.88,
        "min_cost_reduction_ratio": 0.35,
        "requires_security_regression_review": True,
    },
    "refine.focused": {
        "baseline_tier": "mini",
        "candidate_tiers": ["small"],
        "min_average_quality_score": 0.86,
        "min_cost_reduction_ratio": 0.20,
        "requires_security_regression_review": False,
    },
    "refine.section": {
        "baseline_tier": "mid",
        "candidate_tiers": ["mini"],
        "min_average_quality_score": 0.88,
        "min_cost_reduction_ratio": 0.30,
        "requires_security_regression_review": True,
    },
    "regenerate.full": {
        "baseline_tier": "strong",
        "candidate_tiers": ["mid"],
        "min_average_quality_score": 0.92,
        "min_cost_reduction_ratio": 0.20,
        "requires_security_regression_review": True,
    },
    "summary.create": {
        "baseline_tier": "mini",
        "candidate_tiers": ["small"],
        "min_average_quality_score": 0.86,
        "min_cost_reduction_ratio": 0.20,
        "requires_security_regression_review": True,
    },
    "eval.score": {
        "baseline_tier": "small",
        "candidate_tiers": ["small"],
        "min_average_quality_score": 0.90,
        "min_cost_reduction_ratio": 0.00,
        "requires_security_regression_review": True,
    },
}

PROVIDER_GATE_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {
    provider: {} for provider in sorted(REQUIRED_PROVIDERS)
}


def gate_for_operation(operation: str, provider: str | None = None) -> dict[str, Any]:
    if operation not in ROUTE_QUALITY_GATES:
        raise ValueError(f"No route quality gate configured for {operation!r}")
    gate = deepcopy(ROUTE_QUALITY_GATES[operation])
    if provider is not None:
        gate.update(PROVIDER_GATE_OVERRIDES.get(provider, {}).get(operation, {}))
    gate["promotion_rules"] = list(PROMOTION_RULES)
    gate["manual_operator_approval_required"] = True
    return gate


def validate_quality_gate_config() -> None:
    missing = sorted(GENERATION_OPERATIONS - set(ROUTE_QUALITY_GATES))
    if missing:
        raise ValueError(f"Missing route quality gates: {missing}")
    missing_providers = sorted(REQUIRED_PROVIDERS - set(PROVIDER_GATE_OVERRIDES))
    if missing_providers:
        raise ValueError(f"Missing provider gate overrides: {missing_providers}")

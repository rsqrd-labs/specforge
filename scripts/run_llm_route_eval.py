#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_DRY_RUN_ENV_DEFAULTS = {
    "DATABASE_URL": "postgresql+asyncpg://dry-run:dry-run@localhost/specforge",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_PRIVATE_KEY": "dry-run",
    "JWT_PUBLIC_KEY": "dry-run",
    "GOOGLE_CLIENT_ID": "dry-run",
    "GOOGLE_CLIENT_SECRET": "dry-run",
    "FRONTEND_URL": "http://localhost:5173",
    "ANTHROPIC_API_KEY": "",
    "OPENAI_API_KEY": "",
    "GOOGLE_API_KEY": "",
    "ENCRYPTION_MASTER_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "CSRF_SECRET": "dry-run",
    "ENVIRONMENT": "development",
}
for key, value in _DRY_RUN_ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)

from services.llm.quality_gates import (  # noqa: E402
    gate_for_operation,
    validate_quality_gate_config,
)
from services.llm.routing import LLMRoutingError, resolve_llm_route  # noqa: E402
from services.llm.usage import (  # noqa: E402
    estimate_cost_usd,
    estimated_usage_from_text,
)

DEFAULT_DATASET = (
    REPO_ROOT / "docs" / "evals" / "golden_prompts" / "asdd_route_golden.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate provider/tier LLM routes against the ASDD golden set."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--operation", default="all")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--tier", default=None)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Reserved for operator-approved live provider evals. Default is dry-run.",
    )
    args = parser.parse_args()

    validate_quality_gate_config()
    if args.live:
        raise SystemExit(
            "Live route evals are intentionally manual. Run dry-run in CI, then "
            "wire provider calls in an operator-approved branch."
        )

    dataset = _load_dataset(args.dataset)
    selected = _select_cases(dataset, args.operation)
    report = _build_report(
        selected,
        provider=args.provider,
        requested_tier=args.tier,
        operation_filter=args.operation,
    )
    rendered = (
        _render_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, indent=2, sort_keys=True)
    )
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Golden dataset must be a non-empty JSON array")
    for case in data:
        _validate_case(case)
    return data


def _validate_case(case: dict[str, Any]) -> None:
    required = {
        "id",
        "category",
        "operations",
        "problem_statement",
        "upstream_artifacts",
        "expected_traits",
    }
    missing = sorted(required - set(case))
    if missing:
        raise ValueError(f"Golden case missing fields: {missing}")
    traits = case["expected_traits"]
    for field in (
        "required_sections",
        "traceability_required",
        "security_coverage",
        "api_schema_specificity",
        "markdown_code_fence_validity",
        "max_output_chars",
        "reject_expected",
    ):
        if field not in traits:
            raise ValueError(f"Golden case {case['id']} missing trait {field!r}")


def _select_cases(
    dataset: list[dict[str, Any]], operation: str
) -> list[dict[str, Any]]:
    if operation == "all":
        return dataset
    return [case for case in dataset if operation in case["operations"]]


def _build_report(
    cases: list[dict[str, Any]],
    *,
    provider: str,
    requested_tier: str | None,
    operation_filter: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    results = []
    for case in cases:
        for operation in case["operations"]:
            if operation_filter != "all" and operation != operation_filter:
                continue
            gate = gate_for_operation(operation, provider)
            tier = requested_tier or gate["candidate_tiers"][0]
            result = _evaluate_case_operation(
                case,
                operation=operation,
                provider=provider,
                requested_tier=tier,
                gate=gate,
            )
            results.append(result)

    deterministic_pass = all(result["deterministic_pass"] for result in results)
    average_quality = (
        sum(result["quality_score"] for result in results) / len(results)
        if results
        else 0.0
    )
    return {
        "mode": "dry_run",
        "provider": provider,
        "operation_filter": operation_filter,
        "case_count": len(cases),
        "result_count": len(results),
        "average_quality_score": round(average_quality, 4),
        "deterministic_pass": deterministic_pass,
        "manual_operator_approval_required": True,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "results": results,
    }


def _evaluate_case_operation(
    case: dict[str, Any],
    *,
    operation: str,
    provider: str,
    requested_tier: str,
    gate: dict[str, Any],
) -> dict[str, Any]:
    route_error = None
    try:
        route = resolve_llm_route(
            operation=operation,
            preferred_provider=provider,
            requested_tier=requested_tier,
            fallback_tier=gate["baseline_tier"],
            latency_class="offline_eval",
            allow_cross_provider=False,
        )
    except LLMRoutingError as exc:
        route = None
        route_error = str(exc)

    output = _simulated_output(case)
    validator_results = _run_deterministic_validators(case, output)
    usage = None
    estimated_cost = None
    if route is not None:
        usage = estimated_usage_from_text(
            provider=route.provider,
            model=route.model,
            system="ASDD route eval dry-run",
            user=_case_prompt(case),
            output=output,
        )
        estimated_cost = estimate_cost_usd(route.provider, route.model, usage)

    passed = route is not None and all(validator_results.values())
    return {
        "case_id": case["id"],
        "category": case["category"],
        "operation": operation,
        "provider": provider,
        "requested_tier": requested_tier,
        "resolved_route": route.__dict__ if route is not None else None,
        "route_error": route_error,
        "deterministic_validators": validator_results,
        "deterministic_pass": passed,
        "quality_score": _quality_score(validator_results),
        "estimated_cost_usd": float(estimated_cost) if estimated_cost else None,
        "usage_estimation_method": (
            usage.usage_estimation_method if usage is not None else None
        ),
        "promotion_gate": {
            "min_average_quality_score": gate["min_average_quality_score"],
            "min_cost_reduction_ratio": gate["min_cost_reduction_ratio"],
            "manual_operator_approval_required": True,
            "promotion_rules": gate["promotion_rules"],
        },
    }


def _simulated_output(case: dict[str, Any]) -> str:
    traits = case["expected_traits"]
    if traits["reject_expected"]:
        sections = [
            f"## {section}\n\nThis input needs clarification or is unsafe."
            for section in traits["required_sections"]
        ]
        if "Security Rejection" not in output_join(sections):
            sections.append("## Security Rejection\n\nRejected before provider spend.")
        if traits["security_coverage"]:
            coverage = ", ".join(traits["security_coverage"])
            sections.append(f"## Security Coverage\n\n{coverage}.")
        return output_join(sections)
    sections = [
        f"## {section}\n\nDeterministic dry-run coverage."
        for section in traits["required_sections"]
    ]
    if traits["traceability_required"] and "Traceability" not in output_join(sections):
        sections.append("## Traceability Matrix\n\nRequirement-to-artifact mapping.")
    if traits["security_coverage"]:
        coverage = ", ".join(traits["security_coverage"])
        sections.append(f"## Security Coverage\n\n{coverage}.")
    if traits["api_schema_specificity"]:
        fields = ", ".join(traits["api_schema_specificity"])
        sections.append(f"```json\n{{\"entities\": \"{fields}\"}}\n```")
    return "\n\n".join(sections)


def _run_deterministic_validators(case: dict[str, Any], output: str) -> dict[str, bool]:
    traits = case["expected_traits"]
    return {
        "required_sections": all(
            section in output for section in traits["required_sections"]
        ),
        "traceability": (not traits["traceability_required"])
        or "Traceability" in output,
        "security_coverage": all(
            term.lower() in output.lower() for term in traits["security_coverage"]
        ),
        "api_schema_specificity": all(
            term in output for term in traits["api_schema_specificity"]
        ),
        "markdown_code_fences": _code_fences_balanced(output),
        "max_length": len(output) <= int(traits["max_output_chars"]),
        "expected_rejection": (not traits["reject_expected"]) or "Rejection" in output,
    }


def _quality_score(validators: dict[str, bool]) -> float:
    if not validators:
        return 0.0
    passed_count = sum(1 for passed in validators.values() if passed)
    return round(passed_count / len(validators), 4)


def output_join(sections: list[str]) -> str:
    return "\n\n".join(sections)


def _code_fences_balanced(output: str) -> bool:
    return output.count("```") % 2 == 0


def _case_prompt(case: dict[str, Any]) -> str:
    upstream = "\n".join(str(value) for value in case["upstream_artifacts"].values())
    return f"{case['problem_statement']}\n{upstream}".strip()


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# LLM Route Eval Dry-Run",
        "",
        f"- Provider: `{report['provider']}`",
        f"- Results: `{report['result_count']}`",
        f"- Average quality: `{report['average_quality_score']}`",
        f"- Deterministic pass: `{report['deterministic_pass']}`",
        "- Live promotion: manual operator approval required",
        "",
        "| Case | Operation | Route | Quality | Pass |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for result in report["results"]:
        route = result["resolved_route"] or {"model": "unresolved"}
        lines.append(
            f"| {result['case_id']} | {result['operation']} | "
            f"{route['model']} | {result['quality_score']} | "
            f"{result['deterministic_pass']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

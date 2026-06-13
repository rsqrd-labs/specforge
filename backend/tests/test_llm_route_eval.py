from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from services.llm.cost_registry import GENERATION_OPERATIONS, REQUIRED_PROVIDERS
from services.llm.quality_gates import (
    ROUTE_QUALITY_GATES,
    gate_for_operation,
    validate_quality_gate_config,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = (
    REPO_ROOT / "docs" / "evals" / "golden_prompts" / "asdd_route_golden.json"
)
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_llm_route_eval.py"


def _dataset() -> list[dict]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_golden_dataset_covers_major_asdd_prompt_shapes() -> None:
    dataset = _dataset()
    categories = {case["category"] for case in dataset}
    assert {
        "simple_crud_saas",
        "multi_tenant_b2b_workflow",
        "ai_heavy_product",
        "regulated_security_sensitive",
        "vague_prompt_rejection",
        "prompt_injection_rejection",
        "adversarial_prompt_safety_chain",
        "large_context_chain",
    } <= categories

    operations = {op for case in dataset for op in case["operations"]}
    assert {
        "spec.generate",
        "plan.generate",
        "harness.generate",
        "tasks.generate",
        "refine.focused",
        "refine.section",
        "regenerate.full",
        "summary.create",
    } <= operations

    for case in dataset:
        traits = case["expected_traits"]
        assert traits["required_sections"]
        assert isinstance(traits["max_output_chars"], int)
        assert "reject_expected" in traits
        complexity = case["complexity"]
        assert complexity["expected_level"] in {"normal", "high", "critical"}
        assert complexity["expected_tier_floor"] in {None, "mid", "strong"}


def test_golden_dataset_spans_simple_medium_and_complex() -> None:
    dataset = _dataset()
    levels = {case["complexity"]["expected_level"] for case in dataset}
    # Phase 5.3: the corpus must exercise every classifier band so the starting
    # tier (cheap / mid / strong) is validated old-vs-new.
    assert {"normal", "high", "critical"} <= levels


def test_complexity_classifier_matches_corpus_expectations() -> None:
    from services.llm.complexity_classifier import (
        ComplexitySignals,
        classify_complexity,
    )

    for case in _dataset():
        assessment = classify_complexity(
            ComplexitySignals(
                stage_type="spec",
                problem_statement=case["problem_statement"],
                upstream_artifact_count=0,
                upstream_artifacts_text="",
            )
        )
        expected = case["complexity"]
        assert assessment.level == expected["expected_level"], case["id"]
        assert assessment.tier_floor == expected["expected_tier_floor"], case["id"]


def test_route_quality_gates_are_explicit_and_provider_aware() -> None:
    validate_quality_gate_config()
    assert set(ROUTE_QUALITY_GATES) == set(GENERATION_OPERATIONS)
    for provider in REQUIRED_PROVIDERS:
        gate = gate_for_operation("spec.generate", provider)
        assert gate["manual_operator_approval_required"] is True
        assert gate["baseline_tier"]
        assert gate["candidate_tiers"]
        assert gate["min_average_quality_score"] > 0
        assert gate["promotion_rules"]


def test_route_eval_script_dry_run_outputs_report_without_provider_calls() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--operation",
            "spec.generate",
            "--provider",
            "openai",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert report["mode"] == "dry_run"
    assert report["provider"] == "openai"
    assert report["result_count"] >= 1
    assert report["manual_operator_approval_required"] is True
    assert all(item["estimated_cost_usd"] is not None for item in report["results"])
    assert report["classifier_pass"] is True
    assert report["classifier_results"]
    assert all(item["classification_matches"] for item in report["classifier_results"])


def test_route_eval_script_refuses_live_mode_without_operator_workflow() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--live"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "operator-approved" in result.stderr

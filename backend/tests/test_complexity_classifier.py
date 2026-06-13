"""Unit tests for the deterministic complexity classifier (Phase 5.2, issue #26).

The three "anchor" cases below are load-bearing: they pin the two failure modes
the signal set invites — generic-auth false positives and vague-prompt
over-routing — and they mirror the golden corpus (``asdd_route_golden.json``).
"""

from __future__ import annotations

from services.llm.complexity_classifier import (
    ComplexitySignals,
    classify_complexity,
    count_requirement_ids,
    raise_tier_to_floor,
)


def _signals(problem: str, **overrides) -> ComplexitySignals:
    base = {
        "stage_type": "spec",
        "problem_statement": problem,
        "upstream_artifact_count": 0,
        "upstream_artifacts_text": "",
    }
    base.update(overrides)
    return ComplexitySignals(**base)


# --- Anchors -----------------------------------------------------------------


def test_anchor_simple_crud_with_auth_stays_cheap() -> None:
    # "authenticate users" is generic auth — almost every SaaS app has it and it
    # must NOT cross the high threshold.
    assessment = classify_complexity(
        _signals(
            "Build a team task tracker where users create projects, assign tasks, "
            "set due dates, comment, and authenticate users."
        )
    )
    assert assessment.level == "normal"
    assert assessment.tier_floor is None


def test_anchor_vague_short_prompt_stays_cheap() -> None:
    # A short vague prompt yields clarifying questions — cheap work, not a
    # strong-model job.
    assessment = classify_complexity(_signals("Make me an app that makes money fast."))
    assert assessment.level == "normal"
    assert assessment.tier_floor is None


def test_anchor_regulated_health_prompt_raises_to_mid() -> None:
    assessment = classify_complexity(
        _signals(
            "Design a patient intake and triage portal for clinics that collects "
            "symptoms, routes cases to nurses, stores PHI, and integrates with an EHR."
        )
    )
    assert assessment.level == "high"
    assert assessment.tier_floor == "mid"
    assert "regulated_domain" in assessment.reasons


# --- Individual signals ------------------------------------------------------


def test_generic_auth_terms_do_not_trigger_regulated_signal() -> None:
    for term in ("login", "authenticate", "users", "password", "session"):
        assessment = classify_complexity(_signals(f"Build an app with {term} support."))
        assert assessment.tier_floor is None, term


def test_each_regulated_domain_crosses_high_threshold() -> None:
    for term in ("HIPAA", "PCI-DSS", "cardholder data", "PHI", "GDPR", "audit trail"):
        assessment = classify_complexity(
            _signals(f"Build a system that must handle {term} correctly.")
        )
        assert assessment.level == "high", term
        assert assessment.tier_floor == "mid", term


def test_ambiguity_is_gated_behind_length() -> None:
    short = "Make it work somehow, maybe with various features, etc."
    assert classify_complexity(_signals(short)).tier_floor is None

    long_ambiguous = (
        "Build a logistics coordination tool for warehouses. " * 12
        + " The exact routing rules are tbd and may possibly change, "
        "and various other things are not sure yet."
    )
    assessment = classify_complexity(_signals(long_ambiguous))
    assert "ambiguous_long_problem" in assessment.reasons


def test_prior_quality_gate_block_raises_starting_tier() -> None:
    # A retry of a stage the cheap model already failed should start higher even
    # for an otherwise-simple prompt.
    assessment = classify_complexity(
        _signals(
            "Build a simple blog with posts and comments.",
            prior_quality_gate_blocked=True,
        )
    )
    assert assessment.level == "high"
    assert assessment.tier_floor == "mid"
    assert "prior_quality_gate_blocked" in assessment.reasons


def test_harness_and_tasks_carry_a_higher_stage_floor() -> None:
    problem = "Build a moderately involved inventory system with reservations."
    spec = classify_complexity(_signals(problem, stage_type="spec"))
    harness = classify_complexity(_signals(problem, stage_type="harness"))
    assert harness.score > spec.score
    assert "harness_stage_floor" in harness.reasons


def test_large_upstream_chain_adds_integration_weight() -> None:
    upstream = "FR-001 ... " + " ".join(f"FR-{i:03d}" for i in range(1, 40))
    assessment = classify_complexity(
        _signals(
            "Build a platform.",
            stage_type="tasks",
            upstream_artifact_count=3,
            upstream_artifacts_text=upstream,
        )
    )
    assert "many_upstream_artifacts" in assessment.reasons
    assert "many_upstream_requirement_ids" in assessment.reasons


def test_complex_template_slug_adds_weight() -> None:
    assessment = classify_complexity(
        _signals("Build a basic CRUD app.", template_slug="healthcare-portal")
    )
    assert "complex_template" in assessment.reasons


def test_critical_combination_raises_to_strong() -> None:
    problem = (
        "Build a regulated platform handling PHI, PCI-DSS cardholder data, and "
        "HIPAA audit trails. " * 80
        + " The scope is tbd and various things are not sure yet."
    )
    assessment = classify_complexity(_signals(problem))
    assert assessment.level == "critical"
    assert assessment.tier_floor == "strong"


# --- count_requirement_ids ---------------------------------------------------


def test_count_requirement_ids_deduplicates_case_insensitively() -> None:
    text = "FR-001 references FR-001 and fr-001; also NFR-2, SEC-003, AC-10."
    assert count_requirement_ids(text) == 4


def test_count_requirement_ids_empty() -> None:
    assert count_requirement_ids("") == 0
    assert count_requirement_ids("no identifiers here") == 0


# --- raise_tier_to_floor -----------------------------------------------------


def test_raise_tier_to_floor_lifts_cheap_tiers() -> None:
    assert raise_tier_to_floor("small", "mid") == "mid"
    assert raise_tier_to_floor("mini", "mid") == "mid"
    assert raise_tier_to_floor("small", "strong") == "strong"


def test_raise_tier_to_floor_never_lowers_or_no_floor() -> None:
    assert raise_tier_to_floor("mid", "mid") == "mid"
    assert raise_tier_to_floor("strong", "mid") == "strong"  # never lowers
    assert raise_tier_to_floor("mid", None) == "mid"
    assert raise_tier_to_floor("small", None) == "small"

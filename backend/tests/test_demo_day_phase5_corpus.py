"""Phase 5 corpus gate (Demo Day plan §10 Phase 5 / §12).

The repo gates any change to "which artifact gets produced" behind a golden
corpus (``docs/evals/ROUTE_PROMOTION.md``). Demo Day adds its own
problem-statement corpus, ``docs/evals/golden_prompts/demo_day_route_golden.json``
— the *inputs* a live golden run drives, biased to zero-provisioning stacks
(§11.1) so the end-to-end test survives the handoff.

The **live** run (generate the four stages from each problem statement and assert
the construction verifier passes) is the manual promotion gate — it is not run
here, and the flags stay off until it clears (see RUNBOOK §13). What *is*
deterministic, and pinned here, is:

- the corpus is well-formed and uses the route-eval case schema, so it can be fed
  to ``scripts/run_llm_route_eval.py`` unchanged;
- every Demo Day case requires the rubric + scope sections, kept in lock-step with
  ``DEMO_DAY_SECTION_CONTRACTS`` (a contract drift would otherwise let the live
  gate pass on artifacts missing the rubric answers);
- the offline proof that the verifier *can* pass on a representative verified
  package — the corpus gate's pass criterion — which lives in
  ``test_demo_day_phase3.py`` and is referenced here through the public
  ``verify_construction`` so the corpus gate is bound to it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.pipeline.artifact_validator import DEMO_DAY_SECTION_CONTRACTS
from services.pipeline.demo_day_plan_linter import verify_construction

# Repo-root-relative (backend/tests → parents[2] == repo root). In a container
# image that ships only backend/, the docs tree is absent; skip rather than fail
# there (the corpus is a CI-from-repo-root asset).
_CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evals"
    / "golden_prompts"
    / "demo_day_route_golden.json"
)

# Route-eval case schema (mirrors scripts/run_llm_route_eval.py::_validate_case),
# replicated here so the test does not depend on the repo-root scripts/ package
# being importable from backend/.
_REQUIRED_CASE_FIELDS = {
    "id",
    "category",
    "operations",
    "problem_statement",
    "upstream_artifacts",
    "complexity",
    "expected_traits",
}
_REQUIRED_TRAIT_FIELDS = {
    "required_sections",
    "traceability_required",
    "security_coverage",
    "api_schema_specificity",
    "markdown_code_fence_validity",
    "max_output_chars",
    "reject_expected",
}

# The rubric + scope sections that make a Demo Day spec answer the demo-day
# questions — the load-bearing difference from a standard spec. Bare names (the
# corpus convention drops the "## " heading prefix).
_REQUIRED_RUBRIC_SECTIONS = {
    "Demo Day Scope",
    "Out of Scope",
    "AI Usage",
    "Security Posture",
    "Scalability Story",
}


def _load_corpus() -> list[dict]:
    if not _CORPUS_PATH.exists():
        pytest.skip(f"Demo Day corpus not present at {_CORPUS_PATH}")
    data = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data, "corpus must be a non-empty JSON array"
    return data


def test_corpus_cases_match_the_route_eval_schema() -> None:
    cases = _load_corpus()
    seen_ids: set[str] = set()
    for case in cases:
        missing = sorted(_REQUIRED_CASE_FIELDS - set(case))
        assert not missing, f"{case.get('id')}: missing case fields {missing}"
        traits = case["expected_traits"]
        missing_traits = sorted(_REQUIRED_TRAIT_FIELDS - set(traits))
        assert not missing_traits, f"{case['id']}: missing traits {missing_traits}"
        # Ids are unique so a live run can address each case.
        assert case["id"] not in seen_ids, f"duplicate case id {case['id']}"
        seen_ids.add(case["id"])
        # All four stages are generated for a Demo Day package.
        assert {
            "spec.generate",
            "plan.generate",
            "harness.generate",
            "tasks.generate",
        } <= set(case["operations"])


def test_corpus_problem_statements_are_substantive_and_distinct() -> None:
    cases = _load_corpus()
    statements = [c["problem_statement"].strip() for c in cases]
    assert all(len(s) >= 50 for s in statements), "problem statements too thin"
    assert len(set(statements)) == len(statements), "duplicate problem statements"


def test_corpus_requires_the_demo_day_rubric_sections() -> None:
    # Every case must demand the rubric + scope sections, and each of those must be
    # a real section in the live Demo Day spec contract — so the corpus can never
    # drift into accepting artifacts that skip the demo-day answers.
    contract_sections = {
        s.removeprefix("## ") for s in DEMO_DAY_SECTION_CONTRACTS["spec"]
    }
    assert (
        _REQUIRED_RUBRIC_SECTIONS <= contract_sections
    ), "rubric sections drifted from DEMO_DAY_SECTION_CONTRACTS['spec']"
    for case in _load_corpus():
        required = set(case["expected_traits"]["required_sections"])
        assert _REQUIRED_RUBRIC_SECTIONS <= required, (
            f"{case['id']}: missing rubric sections "
            f"{sorted(_REQUIRED_RUBRIC_SECTIONS - required)}"
        )
        # Every required section the corpus names must exist in the contract.
        assert required <= contract_sections, (
            f"{case['id']}: names sections absent from the spec contract: "
            f"{sorted(required - contract_sections)}"
        )


def test_verifier_passes_on_a_representative_verified_package() -> None:
    # The corpus gate's pass criterion (plan §10/§12): a generated package must
    # clear the construction verifier. The full offline proof — a golden verified
    # package plus one mutator per gap kind — lives in test_demo_day_phase3.py.
    # We reference that golden package here through the public verifier so this
    # corpus gate is bound to the same guarantee without duplicating the fixture.
    from tests.test_demo_day_phase3 import _HARNESS, _SPEC, _verified_tasks

    verdict = verify_construction(
        spec=_SPEC,
        plan="",
        harness=_HARNESS,
        tasks=_verified_tasks(),
    )
    assert verdict.verified is True

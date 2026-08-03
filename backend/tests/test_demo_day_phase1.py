"""Demo Day mode — Phase 1 (prompts, section contracts, floors) tests.

The two load-bearing consistency tests (advisor + plan §7.1.1):
  1. Every heading the validator requires for a Demo Day stage is literally
     mandated by that stage's Demo Day system prompt — otherwise validate_sections
     would block every Demo Day generation, or the verifier would silently read
     gaps.
  2. The standard path is byte-identical: ``section_contract`` with the default
     mode returns the unchanged standard contract, and the standard floors are
     untouched (the §4 regression pin).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import prompts.demo_day as dd
from services.pipeline.artifact_validator import (
    DEMO_DAY_SECTION_CONTRACTS,
    SECTION_CONTRACTS,
    IncompleteArtifactError,
    MissingSectionError,
    section_contract,
    validate_artifact_completeness,
    validate_sections,
)

_STAGES = ["spec", "plan", "harness", "tasks"]


# ---------------------------------------------------------------------------
# Consistency: every required heading is mandated by the prompt (§7.1.1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", _STAGES)
def test_demo_day_prompt_mandates_every_contract_heading(stage: str) -> None:
    prompt = dd._demo_day_system_prompt(dd._STAGE_ROLES[stage])
    for heading in DEMO_DAY_SECTION_CONTRACTS[stage]:
        assert heading in prompt, f"{stage} Demo Day prompt is missing {heading!r}"


def test_demo_day_prompt_mandates_parse_stable_task_tokens() -> None:
    prompt = dd._demo_day_system_prompt(dd._STAGE_ROLES["tasks"])
    for token in (
        "### T-NNN:",
        "**Estimated minutes:**",
        "**Precondition:**",
        "**Harness refs:**",
        "AC-NNN",
    ):
        assert token in prompt, f"tasks prompt missing parse-stable token {token!r}"


def test_demo_day_harness_prompt_names_the_e2e_and_matrix() -> None:
    prompt = dd._demo_day_system_prompt(dd._STAGE_ROLES["harness"])
    assert "## End-to-End Smoke Test" in prompt
    assert "## Requirement-to-Test Matrix" in prompt


def test_demo_day_user_prompts_cover_all_stages() -> None:
    for stage in _STAGES:
        out = dd.build_user_prompt(stage, {"problem_statement": "x", "spec": "s"})
        assert "Return only" in out


# ---------------------------------------------------------------------------
# plan-v3 — the demo-readiness stages. One new mandatory section plus four
# amendments folded into existing sections (so they add no new terminal
# MissingSectionError surface); the amendments are prompt text only, so these
# token assertions are the only thing standing between them and a silent
# revert.
# ---------------------------------------------------------------------------


def test_demo_day_plan_prompt_mandates_external_integrations_contract() -> None:
    prompt = dd._demo_day_system_prompt(dd._STAGE_ROLES["plan"])
    assert "## External Integrations and Secrets" in prompt
    for token in ("REAL", "MOCKED", "env var NAME", "on-stage failure plan"):
        assert token in prompt, f"plan prompt missing integrations token {token!r}"


def test_demo_day_plan_prompt_mandates_the_four_folded_stages() -> None:
    prompt = dd._demo_day_system_prompt(dd._STAGE_ROLES["plan"])
    # Deployment surface (Environment and Bootstrap), seed data (Data Model),
    # auth stance (Security Architecture), demo-crash fallbacks (Risks).
    for token in ("DEMO SURFACE", "SEED DATASET", "AUTH STANCE", "DEMO-VISIBLE"):
        assert token in prompt, f"plan prompt missing folded-stage token {token!r}"


def test_demo_day_plan_user_prompt_verifies_the_new_contract() -> None:
    out = dd.build_user_prompt("plan", {"spec": "s"})
    assert "## External Integrations and Secrets" in out
    for token in ("REAL/MOCKED", "Demo surface", "seed rows", "auth stance"):
        assert token in out, f"plan user prompt missing verify token {token!r}"


def test_demo_day_plan_prompt_version_is_bumped() -> None:
    from prompts.base import stage_prompt_version

    assert stage_prompt_version("plan", "demo_day").endswith(":plan-v5")
    # §4 regression pin — the standard plan version is untouched.
    assert stage_prompt_version("plan") == stage_prompt_version("plan", "standard")
    assert ":plan-v5" not in stage_prompt_version("plan")


def test_demo_day_keep_list_carries_integrations_downstream() -> None:
    """The harness cannot mock a boundary the compression dropped."""
    from services.pipeline.prompt_builder import (
        _DEMO_DAY_STAGE_KEEP_SECTIONS,
        _STAGE_KEEP_SECTIONS,
        _keep_sections,
    )

    assert "## External Integrations and Secrets" in _keep_sections("plan", "demo_day")
    # Every kept heading must be a real section of the live contract.
    assert set(_DEMO_DAY_STAGE_KEEP_SECTIONS["plan"]) <= set(
        DEMO_DAY_SECTION_CONTRACTS["plan"]
    )
    # §4 regression pin — the standard keep-list is unchanged.
    assert _keep_sections("plan", "standard") == _STAGE_KEEP_SECTIONS["plan"]
    assert "## External Integrations and Secrets" not in _STAGE_KEEP_SECTIONS["plan"]


# ---------------------------------------------------------------------------
# §4 regression pin — the standard contract selection is byte-identical.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", _STAGES)
def test_standard_section_contract_is_unchanged(stage: str) -> None:
    assert section_contract(stage) == SECTION_CONTRACTS[stage]
    assert section_contract(stage, "standard") == SECTION_CONTRACTS[stage]


@pytest.mark.parametrize("stage", _STAGES)
def test_demo_day_section_contract_selected_by_mode(stage: str) -> None:
    assert section_contract(stage, "demo_day") == DEMO_DAY_SECTION_CONTRACTS[stage]
    assert section_contract(stage, "demo_day") != SECTION_CONTRACTS[stage]


# ---------------------------------------------------------------------------
# validate_sections honours the mode-selected contract.
# ---------------------------------------------------------------------------


def _demo_day_spec_with_all_headings() -> str:
    return "\n\n".join(
        f"{h}\nbody for {h} with enough words to be substantive content here."
        for h in DEMO_DAY_SECTION_CONTRACTS["spec"]
    )


def test_validate_sections_demo_day_passes_with_all_headings() -> None:
    validate_sections("spec", _demo_day_spec_with_all_headings(), {}, "demo_day")


def test_validate_sections_demo_day_blocks_on_missing_heading() -> None:
    artifact = _demo_day_spec_with_all_headings().replace(
        "## Success Demo", "## Removed"
    )
    with pytest.raises(MissingSectionError) as exc:
        validate_sections("spec", artifact, {}, "demo_day")
    assert "## Success Demo" in exc.value.missing


def test_validate_sections_demo_day_does_not_require_standard_headings() -> None:
    # A standard spec heading absent from the lean Demo Day contract must NOT block.
    artifact = _demo_day_spec_with_all_headings()
    assert "## Product Goals" not in artifact
    validate_sections("spec", artifact, {}, "demo_day")  # no raise


# ---------------------------------------------------------------------------
# Demo Day completeness floors (§6.5).
# ---------------------------------------------------------------------------


def _collect_codes(exc: IncompleteArtifactError) -> set[str]:
    return {issue.code for issue in exc.issues}


def test_demo_day_spec_floor_requires_three_fr_and_ac() -> None:
    artifact = (
        _demo_day_spec_with_all_headings()
        + "\n\n## Functional Requirements\nFR-001 only one.\n"
        + "\n## Acceptance Criteria\nAC-001 only one.\n"
    )
    with pytest.raises(IncompleteArtifactError) as exc:
        validate_artifact_completeness("spec", artifact, {}, "demo_day")
    assert "insufficient_requirement_ids" in _collect_codes(exc.value)


def test_demo_day_harness_floor_flags_missing_e2e_test() -> None:
    body = "\n\n".join(
        f"{h}\nsubstantive body content for the {h} section goes here."
        for h in DEMO_DAY_SECTION_CONTRACTS["harness"]
        if h != "## End-to-End Smoke Test"
    )
    # E2E section present but names no test → missing_e2e_smoke_test.
    artifact = body + "\n\n## End-to-End Smoke Test\nWe will smoke test the app.\n"
    with pytest.raises(IncompleteArtifactError) as exc:
        validate_artifact_completeness("harness", artifact, {}, "demo_day")
    assert "missing_e2e_smoke_test" in _collect_codes(exc.value)


def test_demo_day_harness_floor_passes_when_e2e_names_a_test() -> None:
    body = "\n\n".join(
        f"{h}\nsubstantive body content for the {h} section goes here."
        for h in DEMO_DAY_SECTION_CONTRACTS["harness"]
        if h != "## End-to-End Smoke Test"
    )
    artifact = body + (
        "\n\n## End-to-End Smoke Test\nThe smoke test lives at "
        "`tests/e2e/test_smoke.py` and drives the demo journey.\n"
    )
    # Should not raise missing_e2e_smoke_test (other floors may not apply to harness).
    try:
        validate_artifact_completeness("harness", artifact, {}, "demo_day")
    except IncompleteArtifactError as exc:
        assert "missing_e2e_smoke_test" not in _collect_codes(exc)


def test_demo_day_tasks_floor_requires_four_blocks_and_fields() -> None:
    blocks = []
    for i in range(1, 3):  # only 2 blocks, each missing the new fields
        blocks.append(
            f"### T-{i:03d}: Task {i}\n\n**Spec refs:** FR-001\n**Steps**\n1. do it\n"
        )
    artifact = (
        "## Effort Summary\nEstimated build time: ~2h (target ≤ 5h)\n\n"
        "## Build Order\nT-001, T-002\n\n## Traceability Overview\nrows\n\n"
        "## Tasks\n\n" + "\n".join(blocks)
    )
    with pytest.raises(IncompleteArtifactError) as exc:
        validate_artifact_completeness("tasks", artifact, {}, "demo_day")
    codes = _collect_codes(exc.value)
    assert "insufficient_task_count" in codes
    assert "incomplete_task_fields" in codes


# ---------------------------------------------------------------------------
# prompt_builder.build_prompt branches on workspace.mode.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_prompt_selects_demo_day_for_demo_day_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.pipeline import prompt_builder

    monkeypatch.setattr(
        "services.pipeline.prompt_builder.settings.problem_statement_compression",
        False,
    )
    workspace = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        problem_statement="Build a tiny URL shortener prototype for a hackathon demo.",
        provider="anthropic",
        model="claude-haiku-4-5",
        mode="demo_day",
        clarification_qa=None,
    )
    system_prompt, user_prompt, _ = await prompt_builder.build_prompt(
        "spec", workspace, db=None, redis_client=None
    )
    assert "## Demo Day Scope" in system_prompt
    assert "Demo Day SPEC" in user_prompt


@pytest.mark.asyncio
async def test_build_prompt_standard_workspace_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.pipeline import prompt_builder

    monkeypatch.setattr(
        "services.pipeline.prompt_builder.settings.problem_statement_compression",
        False,
    )
    workspace = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000002",
        problem_statement="Build a tiny URL shortener prototype for a hackathon demo.",
        provider="anthropic",
        model="claude-haiku-4-5",
        mode="standard",
        clarification_qa=None,
    )
    system_prompt, _, _ = await prompt_builder.build_prompt(
        "spec", workspace, db=None, redis_client=None
    )
    # Standard spec prompt has the standard heading, not the Demo Day one.
    assert "## Product Goals" in system_prompt
    assert "## Demo Day Scope" not in system_prompt

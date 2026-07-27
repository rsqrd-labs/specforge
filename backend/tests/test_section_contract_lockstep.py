"""Every required section heading must be BOTH declared by its prompt and
extractable by ``_section_body``.

The failure this pins is subtle and has already shipped twice. ``validate_sections``
gates on a plain substring, so ``## Threat Model`` "passes" against an artifact
whose heading reads ``## Threat Model (STRIDE)`` — but ``_section_body`` anchors
to end-of-line, returns ``""``, and every body-based check downstream then reads
the section as empty:

* ``_section_body_issues`` fires a false ``shallow_required_section`` advisory,
* ``plan_coverage_gaps`` silently SKIPS the section (it treats an empty body as
  "absent, validate_sections owns it"), disabling a construction check,
* ``uncovered_requirements`` / the harness matrix checks go quiet the same way.

Audit finding #1 fixed exactly this for ``## Architecture Quality Attribute
Matrix`` by lengthening the contract entry; four more headings carried the same
mismatch afterwards because nothing checked the invariant. This does.
"""

from __future__ import annotations

import re

import pytest

import prompts.demo_day as demo_day_prompts
import prompts.harness as harness_prompts
import prompts.plan as plan_prompts
import prompts.spec as spec_prompts
import prompts.tasks as tasks_prompts
from services.pipeline.artifact_validator import (
    _CONDITIONAL_SECTIONS,
    DEMO_DAY_SECTION_CONTRACTS,
    SECTION_CONTRACTS,
    _section_body,
    validate_sections,
)

_PROMPT_SOURCES = {
    "spec": spec_prompts.SYSTEM_PROMPT,
    "plan": plan_prompts.SYSTEM_PROMPT,
    "harness": harness_prompts.SYSTEM_PROMPT,
    "tasks": tasks_prompts.SYSTEM_PROMPT,
}

_DEMO_DAY_SOURCES = {
    stage: demo_day_prompts._STAGE_ROLES[stage]
    for stage in ("spec", "plan", "harness", "tasks")
}

# A heading suffix the contract entry is allowed to omit: a single balanced
# parenthetical, which `_section_body` resolves via its second pass. Anything
# else (a differing word, a truncated title) is real drift.
_ALLOWED_SUFFIX_RE = re.compile(r"^\s*(?:\([^)\n]*\))?\s*$")


def _declared_suffix(prompt_source: str, heading: str) -> str | None:
    """What the prompt actually writes after ``heading``, or None if the prompt
    never declares it."""
    title = re.escape(heading.lstrip("#").strip())
    match = re.search(rf"(?m)^\s*-?\s*##\s+{title}(?P<suffix>[^\n—]*)", prompt_source)
    return None if match is None else match.group("suffix")


def _contract_cases(
    contracts: dict[str, list[str]], sources: dict[str, str]
) -> list[tuple[str, str, str]]:
    cases = []
    for stage, headings in contracts.items():
        required = list(headings)
        if sources is _PROMPT_SOURCES:
            required += [heading for _, heading in _CONDITIONAL_SECTIONS.get(stage, [])]
        for heading in required:
            cases.append((stage, heading, sources[stage]))
    return cases


_STANDARD_CASES = _contract_cases(SECTION_CONTRACTS, _PROMPT_SOURCES)
_DEMO_DAY_CASES = _contract_cases(DEMO_DAY_SECTION_CONTRACTS, _DEMO_DAY_SOURCES)


@pytest.mark.parametrize(
    ("stage", "heading", "source"),
    _STANDARD_CASES + _DEMO_DAY_CASES,
    ids=[f"{s}:{h}" for s, h, _ in _STANDARD_CASES + _DEMO_DAY_CASES],
)
def test_contract_heading_is_declared_by_its_prompt(
    stage: str, heading: str, source: str
) -> None:
    """A required heading no prompt asks for can never be produced, so the gate
    would block every generation of that stage."""
    suffix = _declared_suffix(source, heading)
    assert suffix is not None, (
        f"{stage} contract requires {heading!r} but its prompt never declares it — "
        "the blocking missing_sections gate would fail every generation"
    )
    assert _ALLOWED_SUFFIX_RE.match(suffix), (
        f"{stage} contract entry {heading!r} does not match the prompt's heading "
        f"{heading + suffix!r}: only a trailing parenthetical may differ"
    )


@pytest.mark.parametrize(
    ("stage", "heading", "source"),
    _STANDARD_CASES + _DEMO_DAY_CASES,
    ids=[f"{s}:{h}" for s, h, _ in _STANDARD_CASES + _DEMO_DAY_CASES],
)
def test_contract_heading_extracts_a_body_from_the_prompts_own_spelling(
    stage: str, heading: str, source: str
) -> None:
    """The presence gate and the body extractor must agree.

    Builds a synthetic artifact using the heading EXACTLY as the prompt writes it
    (parenthetical and all) and asserts both that `validate_sections` accepts it
    and that `_section_body` returns the body — the pair that silently diverged.
    """
    spelled = heading + (_declared_suffix(source, heading) or "").rstrip()
    body = f"substantive body for {heading}"
    artifact = f"{spelled}\n{body}\n\n## Some Later Section\nother\n"
    assert _section_body(artifact, heading) == body, (
        f"{stage}: `_section_body` cannot read {spelled!r} using contract entry "
        f"{heading!r} — the section reads as empty and every body-based check on "
        "it silently disables"
    )


def test_full_contract_document_passes_both_gates() -> None:
    """End-to-end over the whole standard plan contract, the one with every
    parenthesised heading, in the prompt's own spelling."""
    sections = []
    for heading in SECTION_CONTRACTS["plan"]:
        spelled = (
            heading
            + (_declared_suffix(_PROMPT_SOURCES["plan"], heading) or "").rstrip()
        )
        sections.append(f"{spelled}\nbody text for {heading} with real substance.\n")
    artifact = "\n".join(sections)
    validate_sections("plan", artifact, deps={}, mode="standard")
    for heading in SECTION_CONTRACTS["plan"]:
        assert _section_body(artifact, heading), heading


# ---------------------------------------------------------------------------
# The other half of the join: the tasks prompts must ASK for the citations the
# construction verifier reads. A check joining on a token no prompt mandates is
# unsatisfiable, and once enforced marks every package red.
# ---------------------------------------------------------------------------


def test_standard_tasks_prompt_mandates_every_plan_section_c4_checks() -> None:
    from services.pipeline.standard_plan_linter import _STANDARD_PLAN_COVERAGE

    prompt = tasks_prompts.SYSTEM_PROMPT + tasks_prompts.build_user_prompt({})
    for heading in _STANDARD_PLAN_COVERAGE:
        title = heading.lstrip("#").strip()
        assert title in prompt, (
            f"standard C4 plan_coverage requires a task to cite {heading!r}, but "
            "the tasks prompt never names it — the check cannot be satisfied"
        )


def test_demo_day_tasks_prompt_mandates_every_plan_section_c6_checks() -> None:
    from services.pipeline.demo_day_plan_linter import _DEMO_DAY_PLAN_COVERAGE

    prompt = demo_day_prompts._TASKS_ROLE
    for heading in _DEMO_DAY_PLAN_COVERAGE:
        title = heading.lstrip("#").strip()
        assert title in prompt, (
            f"Demo Day C6 plan_coverage requires a task to cite {heading!r}, but "
            "the Demo Day tasks prompt never names it"
        )


def test_standard_tasks_prompt_no_longer_blesses_a_traceability_only_ac() -> None:
    """C1 joins on the Spec refs FIELD. The old checklist explicitly allowed an
    AC to live only in the Traceability Overview, which is the documented-but-
    unbuilt case C1 exists to catch — the two cannot both be right."""
    prompt = tasks_prompts.build_user_prompt({})
    assert "appears in the Traceability Overview or a task's Spec refs" not in prompt
    assert "Appearing only in the Traceability Overview is NOT sufficient" in prompt


def test_demo_day_harness_ref_example_carries_a_file_extension() -> None:
    """Demo Day C2 recognises a path token by its extension; the prompt's own
    sample (`path/to/test_file`) had none, so a model copying it produced refs
    the check could not see."""
    import re as _re

    from services.pipeline.demo_day_plan_linter import _FILE_TOKEN_RE

    prompt = demo_day_prompts._TASKS_ROLE
    line = next(
        line for line in prompt.splitlines() if line.startswith("**Harness refs:**")
    )
    sample = _re.search(r"`([^`]+)`", line)
    assert sample is not None, "the Harness refs line lost its backticked example"
    assert _FILE_TOKEN_RE.search(sample.group(1)), (
        f"example {sample.group(1)!r} has no file extension, so C2's own token "
        "matcher would not recognise it as a harness path"
    )

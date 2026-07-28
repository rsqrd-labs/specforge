from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import EvalResult
from prompts.base import INJECTION_DEFENSE_NOTE, wrap_untrusted_content
from services import langfuse_service
from services.llm.batch_executor import complete_background_llm
from services.llm.cost_ledger import LLMCostContext
from services.llm.gateway import get_llm
from services.llm.output_budget import output_budget_for_operation
from services.llm.provider_config import JUDGE_MODELS
from services.observability import (
    EVAL_POLL_FAILURES,
    UNVERIFIED_COVERAGE_FINDINGS,
    record_judge_call,
)
from services.pipeline.artifact_validator import (
    RELIABLY_PARSED_TEST_EXTS,
    HarnessTestIndex,
    _canonical_test_path,
    _normalise_harness_ref,
    harness_coverage_ratio,
    harness_test_index,
    ref_matches_harness,
)
from services.text_compaction import compact_text

logger = logging.getLogger(__name__)
_EVAL_TIMEOUT_SECONDS = 90.0
_PROMPT_LIMITS: dict[str, tuple[int, int]] = {
    "spec": (0, 28_000),
    "plan": (10_000, 18_000),
    "harness": (10_000, 20_000),
    # Audit H4: a real TASKS.md runs 30–80K chars; the previous 14K artifact
    # bound elided most of it, and the rubric then told the judge to report
    # everything it could not see as a gap. The tasks CONTEXT limit below is
    # the summed budget — spec and harness are bounded separately per part
    # (``_TASKS_CONTEXT_LIMITS``), never concatenated-then-truncated, so the
    # spec can no longer consume the head budget and elide the whole harness.
    "tasks": (16_000, 24_000),
}
_COMPACT_RETRY_LIMITS: dict[str, tuple[int, int]] = {
    "spec": (0, 14_000),
    "plan": (5_000, 9_000),
    "harness": (5_000, 10_000),
    "tasks": (6_000, 10_000),
}
# Per-part bounds for the tasks eval context: (spec_limit, harness_limit),
# keyed by the compact-retry flag. Sums match the tasks context totals above.
_TASKS_CONTEXT_LIMITS: dict[bool, tuple[int, int]] = {
    False: (8_000, 8_000),
    True: (3_000, 3_000),
}

# The tasks eval context is assembled by ``combine_tasks_eval_context`` and
# split back apart (for per-part bounding) on this separator. Producer and
# consumer share these constants so the format cannot drift.
_TASKS_CONTEXT_SPEC_HEADER = "Specification:\n"
_TASKS_CONTEXT_HARNESS_HEADER = "Test harness:\n"
_TASKS_CONTEXT_SEPARATOR = f"\n\n{_TASKS_CONTEXT_HARNESS_HEADER}"


def combine_tasks_eval_context(spec: str, harness: str) -> str:
    """Join spec + harness into the labelled tasks eval context string.

    The single producer for the combined-context format (the shape flows
    through the batch checkpoint rows unchanged, so it stays one string);
    ``_split_tasks_eval_context`` is its inverse for per-part bounding.
    """
    parts = [
        f"{_TASKS_CONTEXT_SPEC_HEADER}{spec}" if spec else "",
        f"{_TASKS_CONTEXT_HARNESS_HEADER}{harness}" if harness else "",
    ]
    return "\n\n".join(part for part in parts if part)


def _split_tasks_eval_context(combined: str) -> tuple[str, str]:
    """Split a combined tasks context back into (spec_part, harness_part).

    Splits on the FIRST occurrence of the harness header boundary: the genuine
    boundary precedes any same-shaped text inside the harness body, and a
    same-shaped line inside the *spec* body merely shifts budget between the
    two parts — both parts are still bounded, so the failure mode is a slightly
    uneven budget, never an unbounded prompt. Headers stay attached to their
    parts. ``harness_part`` is empty when the context has no harness.
    """
    idx = combined.find(_TASKS_CONTEXT_SEPARATOR)
    if idx == -1:
        return combined, ""
    return combined[:idx], combined[idx + 2 :]


# --- Structural task-reference validator ---
_TASK_HEADING_RE = re.compile(r"^###\s+T-(\d+):\s+(.+)$")
_HARNESS_REFS_FIELD_RE = re.compile(r"^\*\*Harness\s+refs:\*\*", re.IGNORECASE)
_BOLD_FIELD_START_RE = re.compile(r"^\*\*\w")
_BACKTICK_REF_RE = re.compile(r"`([^`]+)`")
_SETUP_ONLY_MARKER_RE = re.compile(r"_\(none|none\s*[—–-]", re.IGNORECASE)
# Per-task Priority and Estimate fields (T-164 / T-USE-05).
# Tolerant of bold/colon spacing variations and optional list-marker prefixes.
_PRIORITY_FIELD_RE = re.compile(
    r"^[\s\-*]*\*\*\s*Priority\s*:?\s*\*\*\s*:?\s*(.+?)\s*$", re.IGNORECASE
)
_ESTIMATE_FIELD_RE = re.compile(
    r"^[\s\-*]*\*\*\s*Estimate\s*:?\s*\*\*\s*:?\s*(.+?)\s*$", re.IGNORECASE
)
_PRIORITY_ENUM = {"MUST", "SHOULD", "COULD"}
_ESTIMATE_ENUM = {"S", "M", "L", "XL"}
# The harness-scanner regexes moved to artifact_validator with the scanner.
# Coverage Plan records the harness emits for any category it could not fully
# populate, e.g. `TestCategoryGap: category=performance_budget reason=token_budget
# reqs=FR-012`. A task that references a test in a dropped category is pointing at
# coverage the harness deliberately deferred — a recorded shortfall, not a
# generation defect — so it is reclassified as DEFERRED_COVERAGE, never a hard gap.
_TEST_CATEGORY_GAP_RE = re.compile(
    r"TestCategoryGap:\s*category=([A-Za-z0-9_.\-]+)", re.IGNORECASE
)
# NOTE: the `reqs=`-field scrape that once fed extract_deferred_reqs is gone —
# that field reports *category-depth* trims, not per-requirement gaps, so it
# listed requirements that already had tests. Genuine coverage holes are now
# derived from matrix→file emission in artifact_validator.uncovered_requirements.
# `_TEST_CATEGORY_GAP_RE` (category names) is still used by the task-deferral
# classifier (`_extract_dropped_categories`).
# gap_type values that are not user-facing coverage gaps and must not flag the
# eval: GENERATION_FAILURE (prompt-quality issue, hidden), DEFERRED_COVERAGE (the
# harness recorded the category as deferred under budget — a known,
# surfaced-but-non-blocking shortfall, not a defect), and UNVERIFIED_COVERAGE
# (the referenced FILE exists in the harness but our parser could not extract any
# test identifier from it, so we cannot prove the named test is absent — a
# parser-blind-spot, surfaced quietly rather than as a scary GENUINE_GAP).
_NON_FLAGGING_GAP_TYPES = frozenset(
    {"GENERATION_FAILURE", "DEFERRED_COVERAGE", "UNVERIFIED_COVERAGE"}
)

# Extensions whose test shapes we parse COMPLETELY (moved to
# artifact_validator with the scanner; see RELIABLY_PARSED_TEST_EXTS there
# for the rationale). Aliased for this module's existing call sites.
_RELIABLY_PARSED_EXTS = RELIABLY_PARSED_TEST_EXTS

# Increment whenever deterministic task-finding semantics change. Persisted eval
# rows carry the version that produced their structural findings; GET /eval lazily
# refreshes older task rows against the current harness. This prevents validator
# fixes from leaving already-generated workspaces permanently stuck with stale
# false positives until a user discovers and clicks the manual Re-validate action.
# v2: fence-tolerant/span-based ref extraction, multi-language (Go/RSpec/it.each)
# test parsing, the UNVERIFIED_COVERAGE file-level fallback, and full-canonical
# dropped-category matching — all of which change which refs read as genuine gaps.
STRUCTURAL_TASK_VALIDATOR_VERSION = 2

# eval-v4 (prompt-quality audit 2026-07, H4/L13/L14): the rubric teaches the
# judge about compact_text's elision marker and forbids reporting gaps that
# could fall inside an elided region (H4 — false MissingSection/CoverageGap on
# exactly the largest artifacts); the tasks eval context is bounded per part
# (spec and harness separately) instead of concatenated-then-truncated; the
# tasks template's doubled braces now render as real JSON (L13); and the score
# shape is per-stage — only the dimensions that stage's weighting/completeness
# actually consume are requested (L14). Version history: eval-v3 added the
# shared INJECTION_DEFENSE_NOTE + nonce-fenced artifact/context; eval-v2 was
# the placeholder-safe substitution fix (remediation #1). Both the synchronous
# path and the batch submit path read this constant — never hand-write the
# version string at a call site.
EVAL_PROMPT_VERSION = "eval-v4"

_JUDGE_SYSTEM = (
    "You are an independent senior product and software engineering evaluator. "
    "Score only what is present in the submitted artifact and provided context. "
    "Do not reward implied intent, brand polish, verbosity, or architectural detail "
    "that is not appropriate for the current stage. Be calibrated and conservative: "
    "85+ requires strong, concrete evidence across almost every rubric dimension. "
    "Respond ONLY with valid JSON matching the requested schema. No markdown.\n\n"
    f"{INJECTION_DEFENSE_NOTE}"
)

# The full dimension vocabulary, in the order the score shape lists them.
_ALL_SCORE_DIMENSIONS: tuple[str, ...] = (
    "goal_alignment",
    "requirements_coverage",
    "specificity_testability",
    "user_flow_coverage",
    "non_functional_coverage",
    "traceability",
    "feasibility",
    "clarity",
)
# Dimensions the ``completeness`` roll-up in ``_normalise_eval_payload``
# averages — consumed for every stage, independent of the per-stage weights.
_COMPLETENESS_DIMENSIONS = frozenset(
    {
        "requirements_coverage",
        "user_flow_coverage",
        "non_functional_coverage",
        "traceability",
    }
)

_RUBRIC_HEADER = """
Score each dimension from 0 to 100 using this calibration:
- 0-39: unusable or mostly missing
- 40-59: partial, vague, or materially risky
- 60-74: usable but has notable gaps
- 75-84: good, specific, and mostly complete
- 85-94: excellent with only minor gaps
- 95-100: exceptional, comprehensive, and immediately actionable

Rules:
- Use the full range. Do not default to 85.
- Penalize vague placeholders, contradictions, missing acceptance criteria,
  missing non-functional expectations, and untestable language.
- Prefer concrete, stakeholder-readable requirements over deep implementation
  detail unless the stage explicitly calls for implementation work.
- The provided texts may be bounded: a literal marker like
  "[... N characters omitted for eval budget ...]" means a middle region was
  elided before you received the text. Absence from the visible text is NOT
  absence from the artifact — never list content as a gap, and never lower a
  coverage estimate, on the basis of content that could plausibly fall inside
  an elided region.
- If a requirement, flow, test, or task cannot be found in the visible text
  and no elision marker could account for it, list it as a gap instead of
  assuming it exists.
""".strip()


def score_weights_for(stage_type: str, mode: str = "standard") -> dict[str, float]:
    """The weight table for a (stage, mode) pair.

    Demo Day artifacts answer a different, leaner section contract than standard
    ones, so grading them with the standard weights penalises them for omitting
    sections their contract forbids. Only the SPEC weights actually differ (see
    ``_DEMO_DAY_SCORE_WEIGHTS``); plan/harness/tasks dimensions apply to both
    modes unchanged, and falling through to the standard table keeps them
    byte-identical.
    """
    if mode == "demo_day":
        demo = _DEMO_DAY_SCORE_WEIGHTS.get(stage_type)
        if demo is not None:
            return demo
    return _SCORE_WEIGHTS.get(stage_type, _SCORE_WEIGHTS["spec"])


def _stage_score_dimensions(stage_type: str, mode: str = "standard") -> list[str]:
    """The score dimensions this stage's scoring pipeline actually consumes.

    Audit L14: the rubric used to request all 8 dimensions from every stage
    while the per-stage ``_SCORE_WEIGHTS`` ignore several — wasted judge effort
    and tokens. Consumed = the stage's weighted dimensions ∪ the completeness
    roll-up inputs ∪ clarity, derived from the same structures that do the
    consuming so the request list cannot drift from the scoring code.

    The completeness roll-up inputs are intersected with the mode's weighted
    dimensions plus the standard set: a Demo Day spec must not be *asked* for
    ``user_flow_coverage`` when its contract has no User Journeys section, or
    the judge invents a low score for an absence that is by design.
    """
    weights = score_weights_for(stage_type, mode)
    completeness_inputs = _COMPLETENESS_DIMENSIONS
    if mode == "demo_day" and stage_type in _DEMO_DAY_SCORE_WEIGHTS:
        # Only roll up completeness dimensions this mode actually grades.
        completeness_inputs = _COMPLETENESS_DIMENSIONS & set(weights)
    used = set(weights) | completeness_inputs | {"clarity"}
    # coverage_percent is a separate top-level response field, never a scores key.
    used.discard("coverage_percent")
    return [dim for dim in _ALL_SCORE_DIMENSIONS if dim in used]


def _rubric_for_stage(stage_type: str, mode: str = "standard") -> str:
    score_lines = ",\n".join(
        f'    "{dim}": 0-100' for dim in _stage_score_dimensions(stage_type, mode)
    )
    return (
        f"{_RUBRIC_HEADER}\n\n"
        "Return exactly this JSON shape:\n"
        "{\n"
        '  "scores": {\n'
        f"{score_lines}\n"
        "  },\n"
        '  "coverage_percent": null or 0-100,\n'
        '  "uncovered_reqs": [],\n'
        '  "tasks_without_ref": [],\n'
        '  "risks": []\n'
        "}"
    )


# Plain (non-f) templates: {rubric}, {spec_content}, and {content} are
# substituted in ONE regex pass by _build_eval_prompt, so inserted values are
# never rescanned. Braces in prose therefore need no doubling — the tasks
# template's example object renders as real JSON (audit L13; the doubled-brace
# form leaked `{{"task_number" ...}}` literally to the judge).
_STAGE_PROMPTS: dict[str, str] = {
    "spec": (
        "Evaluate this software specification as a product specification, not an "
        "implementation design. A strong spec defines product goals, user problems, "
        "functional requirements, non-functional requirements, user flows, acceptance "
        "criteria, constraints, success metrics, and high-level system expectations. "
        "It may include high-level conceptual diagrams, but should avoid deep "
        "implementation details.\n\n"
        "{rubric}\n\n"
        "Content:\n{content}"
    ),
    "plan": (
        "Evaluate this implementation plan against the specification. A strong plan "
        "translates spec requirements into coherent work areas, sequencing, risks, "
        "dependencies, validation strategy, and delivery boundaries without losing "
        "traceability to the product goals.\n\n"
        "{rubric}\n\n"
        "Spec:\n{spec_content}\n\nPlan:\n{content}"
    ),
    "harness": (
        "Evaluate this test harness against the specification. A strong harness "
        "covers critical functional requirements, user flows, acceptance criteria, "
        "edge cases, and major non-functional expectations. Set coverage_percent to "
        "your best evidence-based estimate of requirement coverage, and list specific "
        "uncovered requirements.\n\n"
        "{rubric}\n\n"
        "Spec:\n{spec_content}\n\nHarness:\n{content}"
    ),
    "tasks": (
        "Evaluate this task list against the test harness and specification. A strong "
        "task list is complete, sequenced, independently actionable, test-linked, and "
        "traceable. In tasks_without_ref, include objects shaped as "
        '{"task_number": int or null, "task_title": string, "reason": string, '
        '"referenced_test": string or null} for any task that lacks a clear test or '
        "harness reference.\n\n"
        "{rubric}\n\n"
        "Reference context:\n{spec_content}\n\nTasks:\n{content}"
    ),
}

_SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    "spec": {
        "goal_alignment": 0.15,
        "requirements_coverage": 0.25,
        "specificity_testability": 0.20,
        "user_flow_coverage": 0.15,
        "non_functional_coverage": 0.15,
        "clarity": 0.10,
    },
    "plan": {
        "goal_alignment": 0.10,
        "requirements_coverage": 0.20,
        "specificity_testability": 0.15,
        "traceability": 0.20,
        "feasibility": 0.20,
        "clarity": 0.15,
    },
    "harness": {
        "requirements_coverage": 0.30,
        "specificity_testability": 0.20,
        "traceability": 0.20,
        "coverage_percent": 0.20,
        "clarity": 0.10,
    },
    "tasks": {
        "requirements_coverage": 0.20,
        "specificity_testability": 0.20,
        "traceability": 0.25,
        "feasibility": 0.20,
        "clarity": 0.15,
    },
}

# Demo Day overrides, applied per stage by ``score_weights_for``. Only the SPEC
# differs: ``DEMO_DAY_SECTION_CONTRACTS["spec"]`` has no User Journeys / User
# Flow Diagrams section — Demo Day deliberately specifies exactly ONE happy path
# (``## Success Demo``) — so scoring ``user_flow_coverage`` at 0.15 docked every
# Demo Day spec for obeying its own contract. Its weight is redistributed across
# the three dimensions Demo Day actually asks for.
#
# ``non_functional_coverage`` is deliberately KEPT (and kept at 0.15): a Demo Day
# spec carries no NFR-NNN ids, but it does carry the ``## AI Usage`` /
# ``## Security Posture`` / ``## Scalability Story`` rubric sections, which are
# non-functional concerns. The Demo Day stage prompt below re-points the judge at
# those sections so the dimension grades something real instead of a missing
# heading. plan/harness/tasks are absent here on purpose — their dimensions apply
# to both modes, so they fall through to the standard table unchanged.
_DEMO_DAY_SCORE_WEIGHTS: dict[str, dict[str, float]] = {
    "spec": {
        "goal_alignment": 0.20,
        "requirements_coverage": 0.30,
        "specificity_testability": 0.25,
        "non_functional_coverage": 0.15,
        "clarity": 0.10,
    },
}

# Demo Day stage prompts. Same {rubric}/{spec_content}/{content} placeholders and
# the same single-pass substitution, so they are drop-in replacements. Each one
# names the Demo Day section contract explicitly: a judge that does not know the
# artifact was written to a leaner contract reports every standard-only section
# as a gap, which is precisely the false-alarm class the critic already fixed for
# itself (critic._demo_day_per_stage_focus) and the eval had not.
_DEMO_DAY_STAGE_PROMPTS: dict[str, str] = {
    "spec": (
        "Evaluate this DEMO DAY specification. It is deliberately scoped to a "
        "buildable-in-one-sitting demo, NOT a full product spec, and answers a "
        "leaner contract: Overview, Target User and Core Problem, Demo Day Scope, "
        "Out of Scope, Functional Requirements (FR-NNN), Acceptance Criteria "
        "(AC-NNN), Success Demo, AI Usage, Security Posture, Scalability Story, "
        "Risks and Assumptions. It carries NO NFR-NNN or SEC-NNN identifiers and "
        "NO User Journeys or User Flow Diagrams section — do not treat their "
        "absence as a gap. Score non_functional_coverage against the AI Usage, "
        "Security Posture, and Scalability Story sections: reward named, specific "
        "controls and choices, and penalise adjectives and generic filler. A "
        "single, concrete, end-to-end happy path in Success Demo is the correct "
        "answer, not a coverage shortfall.\n\n"
        "{rubric}\n\n"
        "Content:\n{content}"
    ),
    "plan": (
        "Evaluate this DEMO DAY implementation plan against its specification. A "
        "strong Demo Day plan is buildable in one sitting and leaves nothing to "
        "interpretation: exact interface contracts, data shapes, field names and "
        "types; a real, copy-pasteable bootstrap; an explicit REAL-or-MOCKED "
        "stance plus an env-var name for every external integration. It tracks "
        "FR-NNN/AC-NNN only (no NFR/SEC ids) and its Architecture Decision "
        "Records use the short Demo Day shape — decision, cheap-now choice, "
        "alternative rejected and why, and how it scales/secures — not the "
        "standard five-line ADR. Judge cheap-and-concrete as correct; penalise "
        "vagueness and over-engineering equally.\n\n"
        "{rubric}\n\n"
        "Spec:\n{spec_content}\n\nPlan:\n{content}"
    ),
    "harness": (
        "Evaluate this DEMO DAY test harness against its specification. A strong "
        "Demo Day harness maps every FR-NNN/AC-NNN to a named test in the "
        "Requirement-to-Test Matrix and defines one unmockable end-to-end smoke "
        "test that drives the Success Demo journey. Demo Day does NOT mandate the "
        "standard integration/security/contract/migration_safety test categories "
        "— do not report their absence as a gap. Set coverage_percent to your "
        "best evidence-based estimate of requirement coverage, and list specific "
        "uncovered requirements.\n\n"
        "{rubric}\n\n"
        "Spec:\n{spec_content}\n\nHarness:\n{content}"
    ),
    "tasks": (
        "Evaluate this DEMO DAY task list against the test harness and "
        "specification. A strong Demo Day task list stands up a walking skeleton "
        "first, keeps the end-to-end smoke test green from the first task "
        "onwards, and orders tasks so each Precondition names only earlier tasks. "
        "In tasks_without_ref, include objects shaped as "
        '{"task_number": int or null, "task_title": string, "reason": string, '
        '"referenced_test": string or null} for any task that lacks a clear test '
        "or harness reference. A deliberately small task count is correct for a "
        "one-sitting build, not a completeness gap.\n\n"
        "{rubric}\n\n"
        "Reference context:\n{spec_content}\n\nTasks:\n{content}"
    ),
}


def _stage_prompt_template(stage_type: str, mode: str = "standard") -> str:
    """The eval prompt template for a (stage, mode) pair."""
    if mode == "demo_day":
        demo = _DEMO_DAY_STAGE_PROMPTS.get(stage_type)
        if demo is not None:
            return demo
    return _STAGE_PROMPTS[stage_type]


def _parse_task_blocks(tasks_content: str) -> list[dict[str, Any]]:
    """Split tasks content into per-task dicts with harness_refs extracted.

    harness_refs values:
      None  — **Harness refs:** field is absent (GENERATION_FAILURE)
      []    — field present but marked as setup-only
      [str] — list of backtick-quoted test path references
    """
    lines = tasks_content.split("\n")
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _TASK_HEADING_RE.match(line.rstrip())
        if m:
            headings.append((i, int(m.group(1)), m.group(2).strip()))

    tasks: list[dict[str, Any]] = []
    for idx, (start, task_num, task_title) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        block = lines[start:end]

        refs_start: int | None = None
        for i, line in enumerate(block):
            if _HARNESS_REFS_FIELD_RE.match(line):
                refs_start = i
                break

        if refs_start is None:
            tasks.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "harness_refs": None,
                }
            )
            continue

        field_lines: list[str] = []
        for i, line in enumerate(block[refs_start:]):
            stripped = line.strip()
            if i > 0 and (
                _BOLD_FIELD_START_RE.match(stripped) or stripped.startswith("###")
            ):
                break
            field_lines.append(line)

        refs_text = "\n".join(field_lines)
        if _SETUP_ONLY_MARKER_RE.search(refs_text):
            tasks.append(
                {"task_number": task_num, "task_title": task_title, "harness_refs": []}
            )
            continue

        tasks.append(
            {
                "task_number": task_num,
                "task_title": task_title,
                "harness_refs": _BACKTICK_REF_RE.findall(refs_text),
            }
        )

    return tasks


# The harness ref scanner now lives in `artifact_validator` so the
# construction verifier joins on the SAME multi-language index this
# validator does (it previously had only a Python-only view). Behaviour
# here is unchanged: these are aliases for the moved names.
_HarnessRefIndex = HarnessTestIndex
_harness_ref_index = harness_test_index


def _extract_harness_refs(harness_content: str) -> set[str]:
    """Matchable test identifiers from harness file headings and code blocks.

    Thin wrapper over :func:`_harness_ref_index` preserving the historical
    ``set[str]`` contract for callers (and tests) that only need ``known_refs``.
    """
    return _harness_ref_index(harness_content).known_refs


# `_normalise_harness_ref` / `ref_matches_harness` moved to
# `artifact_validator` alongside the scanner that produces the refs they
# match against (one home for the join keys). Aliased here so this module's
# ~30 internal call sites and the existing tests keep their private names.
_ref_matches_harness = ref_matches_harness


def _normalise_category_token(value: str) -> str:
    """Lowercase and drop all separators for category↔filename comparison."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _extract_dropped_categories(harness_content: str) -> set[str]:
    """Normalised names of every category the harness recorded as deferred.

    Parses the ``TestCategoryGap: category=<name> …`` Coverage Plan records the
    harness emits for any reduced/dropped category. Both ``reason=token_budget``
    and ``reason=other`` count — either way the tests were not generated.
    """
    return {
        token
        for m in _TEST_CATEGORY_GAP_RE.finditer(harness_content)
        if (token := _normalise_category_token(m.group(1)))
    }


def extract_deferred_reqs(harness_content: str) -> list[str]:
    """Requirement IDs with a genuine coverage hole — the honest gap set.

    Delegates to :func:`artifact_validator.uncovered_requirements`, which reads
    the Requirement-to-Test Matrix and reports only requirements whose every
    mapped test file is absent from the ``## Files`` section. This is the single
    source of truth consumed by both the GET-eval response (to surface a coverage
    gap to the user) and the ``regenerate-gaps`` endpoint (to actually patch
    them), so the surfaced set and the patched set never diverge.

    It replaces the previous ``TestCategoryGap reqs=`` scrape, which reported
    *category-depth* trims as per-requirement gaps and so listed requirements
    that already had at least one emitted test (e.g. a requirement whose
    accessibility tier was thinned but whose integration test exists). On a fully
    emitted harness this returns ``[]`` — no false "you have missing coverage"
    panel — and the paid patch only ever regenerates tests that genuinely do not
    exist.
    """
    # Imported lazily to avoid a circular import at module load (the validator
    # imports nothing from evals, but evals → pipeline is the established edge).
    from services.pipeline.artifact_validator import (  # noqa: PLC0415
        uncovered_requirements,
    )

    return uncovered_requirements(harness_content)


def _ref_in_dropped_category(ref: str, dropped_categories: set[str]) -> bool:
    """True only when the ref's *file* belongs to a recorded dropped category.

    Conservative by design (the masking direction is the dangerous one): we match
    the file-path component before ``::``, not the test/method name, because
    category→filename is the harness's structural convention while
    category→method-name is coincidence. The match is by EQUALITY against the
    path's meaningful tokens — each ``/``-separated segment as a whole (so a
    multi-word category like ``performance_budget`` matches a
    ``performance_budget/`` directory) AND each segment split further on ``._-``
    into sub-words (so a single-word category like ``accessibility`` matches both
    an ``accessibility/`` directory and a ``test_accessibility.py`` filename). It
    is deliberately NOT a raw substring test on the separator-collapsed path: that
    let an accidental substring (``unit`` inside ``comm-unit-y``) silently
    reclassify an unrelated real gap as deferred — the one failure mode that
    matters here (masking a genuine hole).
    """
    if not dropped_categories:
        return False
    normalized = ref.strip().replace("\\", "/")
    if normalized.startswith("harness/"):
        normalized = normalized[len("harness/") :]
    file_part = normalized.split("::", 1)[0]
    tokens: set[str] = set()
    for segment in file_part.split("/"):
        # Whole-segment token from the stem (extension chain stripped) so a
        # multi-word category matches a compound filename:
        # ``performance_budget.test.ts`` -> stem ``performance_budget`` ->
        # ``performancebudget``. Directory segments have no ``.`` and are
        # unaffected.
        stem = segment.split(".", 1)[0]
        seg_token = _normalise_category_token(stem)
        if seg_token:
            tokens.add(seg_token)
        # Each sub-word (so a single-word category matches one component of a
        # compound name, ``accessibility`` in ``test_accessibility.py``) PLUS
        # every contiguous join of adjacent sub-words. The joins let a multi-word
        # category match a filename that wraps it in an affix or extra words —
        # ``performance_budget`` matches the pytest-default ``test_performance_
        # budget.py`` and the Go ``performance_budget_test.go`` (the stem-only
        # token there is ``testperformancebudget`` / ``performancebudgettest``,
        # neither of which equals the category). Still equality-based, so the
        # ``community`` ⊅ ``unit`` masking fix holds: no join of {community, test}
        # ever equals ``unit`` (Fable verify #3).
        words = [w for w in re.split(r"[._\-]+", segment) if w]
        for word in words:
            word_token = _normalise_category_token(word)
            if word_token:
                tokens.add(word_token)
        for i in range(len(words)):
            for j in range(i + 2, len(words) + 1):
                joined = _normalise_category_token("".join(words[i:j]))
                if joined:
                    tokens.add(joined)
    return any(cat in tokens for cat in dropped_categories)


def _build_gap_details(
    missing_ref: str,
) -> tuple[str | None, str | None, str, str | None, str]:
    """Parse a missing test ref into actionable details.

    Returns (harness_file, class_name, fn_name, code_stub, remediation_text).
    """
    normalized = _normalise_harness_ref(missing_ref)

    parts = normalized.split("::")

    if len(parts) == 1 and re.fullmatch(r"[^\s`]+\.[A-Za-z0-9]+", normalized):
        # Whole-file reference. Do not suggest a syntactically impossible
        # ``def tests/path.spec.ts()`` stub when the actual missing artifact is
        # the file itself.
        harness_file = f"harness/{normalized}"
        class_name = None
        fn_name = normalized.rsplit("/", 1)[-1]
        code_stub = None
        remediation = f"Add the missing harness file `{harness_file}`."
    elif len(parts) == 3 and "/" in parts[0]:
        # file::Class::method
        file_path, class_name, fn_name = parts[0], parts[1], parts[2]
        harness_file = f"harness/{file_path}"
        code_stub = f"class {class_name}:\n    def {fn_name}(self):\n        pass"
        remediation = (
            f"In `{harness_file}`, add `def {fn_name}(self)` "
            f"to the `{class_name}` class."
        )
    elif len(parts) == 2 and "/" in parts[0]:
        # file::function
        file_path, fn_name = parts[0], parts[1]
        harness_file = f"harness/{file_path}"
        class_name = None
        code_stub = f"def {fn_name}():\n    pass"
        remediation = f"In `{harness_file}`, add `def {fn_name}()`."
    elif len(parts) == 2:
        # Class::method (no file path)
        class_name, fn_name = parts[0], parts[1]
        harness_file = None
        code_stub = f"class {class_name}:\n    def {fn_name}(self):\n        pass"
        remediation = (
            f"Add `def {fn_name}(self)` to the `{class_name}` class in your harness."
        )
    else:
        # bare function name
        fn_name = parts[0]
        harness_file = None
        class_name = None
        code_stub = f"def {fn_name}():\n    pass"
        remediation = f"Add `def {fn_name}()` to a test file in your harness."

    return harness_file, class_name, fn_name, code_stub, remediation


def _extract_field_value(line: str, regex: re.Pattern[str]) -> str | None:
    """Pull the value after **Field:** from a single line, stripped of formatting."""
    match = regex.match(line.rstrip())
    if not match:
        return None
    value = match.group(1).strip()
    # Trim trailing parenthetical commentary (e.g. "MUST (ship blocker)").
    paren = value.find("(")
    if paren > 0:
        value = value[:paren].strip()
    # Strip surrounding markdown emphasis, backticks, and trailing punctuation.
    value = value.strip("`*_ .,;")
    return value or None


def _validate_task_fields(tasks_content: str) -> list[dict[str, Any]]:
    """Per-task Priority/Estimate validation (T-USE-05).

    Returns one issue per missing or invalid field, shaped to merge cleanly into
    the existing tasks_without_ref list. Issues are surfaced in the existing
    TaskValidationPanel UI without any shape change.
    """
    lines = tasks_content.split("\n")
    headings: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = _TASK_HEADING_RE.match(line.rstrip())
        if m:
            headings.append((i, int(m.group(1)), m.group(2).strip()))

    issues: list[dict[str, Any]] = []
    for idx, (start, task_num, task_title) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        block = lines[start:end]

        priority_value: str | None = None
        estimate_value: str | None = None
        for line in block:
            if priority_value is None:
                priority_value = _extract_field_value(line, _PRIORITY_FIELD_RE)
            if estimate_value is None:
                estimate_value = _extract_field_value(line, _ESTIMATE_FIELD_RE)
            if priority_value is not None and estimate_value is not None:
                break

        if priority_value is None or priority_value.upper() not in _PRIORITY_ENUM:
            reason = (
                "Task is missing a **Priority:** line."
                if priority_value is None
                else (
                    f"`{priority_value}` is not a valid Priority "
                    "(expected MUST/SHOULD/COULD)."
                )
            )
            issues.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "reason": reason,
                    "referenced_test": None,
                    "gap_type": "MISSING_PRIORITY",
                    "remediation": (
                        "Add `**Priority:** MUST` (or SHOULD/COULD) to this task."
                    ),
                    "harness_file": None,
                    "code_stub": None,
                }
            )

        if estimate_value is None or estimate_value.upper() not in _ESTIMATE_ENUM:
            reason = (
                "Task is missing an **Estimate:** line."
                if estimate_value is None
                else f"`{estimate_value}` is not a valid Estimate (expected S/M/L/XL)."
            )
            issues.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "reason": reason,
                    "referenced_test": None,
                    "gap_type": "MISSING_ESTIMATE",
                    "remediation": ("Add `**Estimate:** S` (or M/L/XL) to this task."),
                    "harness_file": None,
                    "code_stub": None,
                }
            )

    return issues


def _classify_unmatched_ref(
    ref: str,
    index: _HarnessRefIndex,
    dropped_categories: set[str],
) -> str:
    """Classify one unmatched TASKS harness ref into a gap_type.

    Ordered strictest-last so the loud surface stays high-precision (bias rule C):
      * DEFERRED_COVERAGE — the ref's file is in a category the harness explicitly
        recorded as deferred. Actionable, non-blocking.
      * UNVERIFIED_COVERAGE — the ref's FILE exists as a ``### File:`` heading with
        a non-empty body we could not read (a language we don't fully parse), so
        we cannot prove the named test is absent. Parser-blind-spot, not a hole —
        surfaced quietly, not as a scary gap.
      * GENUINE_GAP — positive evidence of absence: the file does not exist; OR it
        exists but is completely empty (no fenced body at all); OR it is a
        reliably-parsed Python file with zero test definitions; OR we DID parse
        tests from it and the named one is not among them.
    """
    if _ref_in_dropped_category(ref, dropped_categories):
        return "DEFERRED_COVERAGE"
    file_canon = _canonical_test_path(ref)
    if file_canon in index.known_files and file_canon not in index.files_with_tests:
        # File heading exists but we parsed zero tests from it. Demote to the
        # quiet UNVERIFIED class ONLY when the parser was genuinely blind. When we
        # have positive evidence of absence, keep it a loud GENUINE_GAP so a real
        # hole is never hidden (the primary directive — do not over-suppress):
        #   * no fenced body at all → the file was promised but left empty; the
        #     strongest, language-agnostic gap signal.
        #   * a readable .py file with zero tests → we parse pytest/unittest
        #     completely, so zero matches IS absence.
        empty_file = file_canon not in index.files_with_body
        reliably_parsed = file_canon.endswith(_RELIABLY_PARSED_EXTS)
        if empty_file or reliably_parsed:
            return "GENUINE_GAP"
        return "UNVERIFIED_COVERAGE"
    return "GENUINE_GAP"


def _validate_task_references(
    tasks_content: str, harness_content: str
) -> list[dict[str, Any]]:
    """Structural traceability check: returns issues with gap_type classification.

    GENERATION_FAILURE — task has no **Harness refs:** field (prompt quality issue,
      hidden from users but logged for observability).
    GENUINE_GAP — task refs a test that does not exist in the harness (shown to user).
    DEFERRED_COVERAGE — the unmatched ref belongs to a category the harness
      explicitly recorded as deferred (TestCategoryGap). Non-blocking note.
    UNVERIFIED_COVERAGE — the unmatched ref's file exists but our parser could not
      read any test from it, so absence is unproven. Non-blocking, quiet.

    Precedence on a mixed task is GENUINE_GAP > DEFERRED_COVERAGE >
    UNVERIFIED_COVERAGE: a single genuinely-missing test is never masked by a
    deferred or unparseable sibling ref, but a task with no genuine gap surfaces
    quietly rather than manufacturing a false alarm.
    """
    task_blocks = _parse_task_blocks(tasks_content)
    index = _harness_ref_index(harness_content)
    known_refs = index.known_refs
    dropped_categories = _extract_dropped_categories(harness_content)

    issues: list[dict[str, Any]] = []
    generation_failures: list[int] = []
    unverified_count = 0

    for task in task_blocks:
        refs = task["harness_refs"]
        task_num = task["task_number"]
        task_title = task["task_title"]

        if refs is None:
            generation_failures.append(task_num)
            issues.append(
                {
                    "task_number": task_num,
                    "task_title": task_title,
                    "reason": "Task is missing its Harness refs field.",
                    "referenced_test": None,
                    "gap_type": "GENERATION_FAILURE",
                    "remediation": None,
                    "harness_file": None,
                    "code_stub": None,
                }
            )
        elif refs:
            unmatched = [r for r in refs if not _ref_matches_harness(r, known_refs)]
            if unmatched:
                classified = [
                    (r, _classify_unmatched_ref(r, index, dropped_categories))
                    for r in unmatched
                ]
                genuine = [r for r, kind in classified if kind == "GENUINE_GAP"]
                deferred = [r for r, kind in classified if kind == "DEFERRED_COVERAGE"]
                unverified = [
                    r for r, kind in classified if kind == "UNVERIFIED_COVERAGE"
                ]
                if genuine:
                    missing = genuine[0]
                    harness_file, class_name, fn_name, code_stub, remediation = (
                        _build_gap_details(missing)
                    )
                    issues.append(
                        {
                            "task_number": task_num,
                            "task_title": task_title,
                            "reason": (
                                f"`{missing}` is referenced but not found "
                                "in the harness."
                            ),
                            "referenced_test": missing,
                            "gap_type": "GENUINE_GAP",
                            "remediation": remediation,
                            "harness_file": harness_file,
                            "code_stub": code_stub,
                        }
                    )
                elif deferred:
                    deferred_ref = deferred[0]
                    harness_file, _cls, _fn, _stub, _rem = _build_gap_details(
                        deferred_ref
                    )
                    issues.append(
                        {
                            "task_number": task_num,
                            "task_title": task_title,
                            "reason": (
                                f"`{deferred_ref}` belongs to a test category the "
                                "harness deferred under its token budget "
                                "(recorded as a TestCategoryGap), so it was not "
                                "generated yet."
                            ),
                            "referenced_test": deferred_ref,
                            "gap_type": "DEFERRED_COVERAGE",
                            "remediation": (
                                "This coverage was intentionally deferred by the "
                                "harness under its token budget, not lost. Open the "
                                "HARNESS stage and use its free Regenerate to "
                                "generate the deferred tests, or mark this task "
                                "setup-only if the deferral is acceptable for now."
                            ),
                            "harness_file": harness_file,
                            "code_stub": None,
                        }
                    )
                else:
                    unverified_count += 1
                    ref = unverified[0]
                    harness_file, _cls, _fn, _stub, _rem = _build_gap_details(ref)
                    issues.append(
                        {
                            "task_number": task_num,
                            "task_title": task_title,
                            "reason": (
                                f"`{ref}` names a harness file that exists, but its "
                                "individual tests could not be parsed for automatic "
                                "verification (an unusual code-fence or a language "
                                "the checker does not read)."
                            ),
                            "referenced_test": ref,
                            "gap_type": "UNVERIFIED_COVERAGE",
                            "remediation": (
                                "The referenced file is present in the harness. Open "
                                "the HARNESS stage to confirm the test exists — this "
                                "is a checker limitation, not a confirmed gap."
                            ),
                            "harness_file": harness_file,
                            "code_stub": None,
                        }
                    )
        # refs == [] means setup-only — not an issue

    if unverified_count:
        UNVERIFIED_COVERAGE_FINDINGS.inc(unverified_count)

    if generation_failures:
        logger.warning(
            "tasks_structural_validation_generation_failures count=%d task_numbers=%s",
            len(generation_failures),
            generation_failures[:10],
        )

    issues.extend(_validate_task_fields(tasks_content))

    return issues


def validate_stage_findings(
    stage_type: str,
    content: str,
    harness_content: str | None,
) -> tuple[list[dict[str, Any]] | None, bool]:
    """Deterministic structural findings for a stage — no judge call.

    Extracted from ``_persist_eval_data`` (issue #27 Phase 1) so both the
    post-generation flow and ``POST /stages/{id}/revalidate-tasks`` derive task
    traceability from one place.  Pure regex parsing, microsecond-cheap, and
    fully independent of any LLM score.

    Returns ``(tasks_without_ref, flagged)``:
      * ``tasks_without_ref`` — the structural task→harness traceability and
        per-task field issues for a TASKS stage validated against its harness.
        ``None`` for any other stage type or when there is no harness content to
        validate against (the judge's fallback list, if any, is layered on by
        ``_persist_eval_data`` only in that case).
      * ``flagged`` — ``True`` only when at least one *genuine* gap is present.
        A ``GENERATION_FAILURE`` is a prompt-quality issue, not a user-facing
        flag.  Harness ``coverage_percent`` flagging is LLM-derived and stays in
        ``_persist_eval_data`` — it is deliberately not produced here.
    """
    if stage_type != "tasks" or not harness_content:
        return None, False
    tasks_without_ref = _validate_task_references(content, harness_content)
    flagged = any(
        issue.get("gap_type") not in _NON_FLAGGING_GAP_TYPES
        for issue in tasks_without_ref
    )
    return tasks_without_ref, flagged


async def _get_or_create_eval(
    db: AsyncSession, stage_version_id: UUID, stage_type: str
) -> EvalResult:
    """Return the latest EvalResult for a version, or a fresh unpersisted one.

    One eval row per stage version: the inline structural persist
    (``persist_structural_eval``) creates the row with score fields null, and a
    later sampled or batched judge score updates *that* row instead of racing a
    second copy.  Mirrors the find-or-update pattern in
    ``POST /stages/{id}/revalidate-tasks`` (issue #27 Phase 1).  A stage version
    is immutable, so there is exactly one logical eval per version.
    """
    result = await db.execute(
        select(EvalResult)
        .where(EvalResult.stage_version_id == stage_version_id)
        .order_by(EvalResult.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    return EvalResult(stage_version_id=stage_version_id, stage_type=stage_type)


async def persist_structural_eval(
    db: AsyncSession,
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    harness_content: str | None,
) -> EvalResult:
    """Persist deterministic structural findings inline — no judge call.

    Runs after a stage clears its quality gate and *before* (and independent of)
    any LLM score (issue #27 Phase 1).  Score fields stay null; only the
    deterministic traceability findings are populated, so the workspace gets
    actionable task gaps immediately without waiting on — or paying for — a
    judge round trip.  Find-or-update by version so a later sampled judge score
    updates this same row.  Score fields already present on the row (e.g. a
    re-persist) are preserved, never nulled.
    """
    tasks_without_ref, flagged = validate_stage_findings(
        stage_type, content, harness_content
    )
    eval_result = await _get_or_create_eval(db, stage_version_id, stage_type)
    eval_result.stage_type = stage_type
    eval_result.tasks_without_ref = tasks_without_ref
    eval_result.flagged = flagged
    if stage_type == "tasks" and harness_content:
        eval_result.structural_validator_version = STRUCTURAL_TASK_VALIDATOR_VERSION
    db.add(eval_result)
    await db.commit()
    await db.refresh(eval_result)
    return eval_result


def _log_dataset_error(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        logger.error("langfuse_dataset_background_failed", extra={"error": str(exc)})


def _score_comment(
    stage_type: str,
    generation_provider: str | None,
    generation_model: str | None,
) -> str | None:
    """Compact provider/model tag for the Langfuse score row (issue #27 Phase 5).

    The score already links to its generation observation (which carries the
    true route provider/model), so this is human-readable redundancy in the
    score view itself — enough to compare model/provider quality at a glance
    without joining to the observation.  Returns ``None`` (no comment) when the
    generation route is unknown.
    """
    if generation_provider is None and generation_model is None:
        return None
    route = "/".join(part for part in (generation_provider, generation_model) if part)
    return f"{stage_type} · {route}"


def _dataset_for_score(score: int | float | None) -> str | None:
    if score is None:
        return None
    if score >= 85:
        return "high_quality_generations"
    if score < 60:
        return "low_quality_generations"
    return None


def _clamp_score(value: Any) -> int | None:
    if value is None:
        return None
    try:
        score = round(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _weighted_score(
    values: dict[str, int | None], weights: dict[str, float]
) -> int | None:
    weighted_total = 0.0
    weight_total = 0.0
    for key, weight in weights.items():
        score = values.get(key)
        if score is None:
            continue
        weighted_total += score * weight
        weight_total += weight
    if weight_total == 0:
        return None
    return round(weighted_total / weight_total)


def _average_score(*scores: int | None) -> int | None:
    present = [score for score in scores if score is not None]
    if not present:
        return None
    return round(sum(present) / len(present))


def _normalise_task_issues(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    issues: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        task_number = item.get("task_number")
        if task_number is not None:
            try:
                task_number = int(task_number)
            except (TypeError, ValueError):
                task_number = None
        task_title = item.get("task_title") or item.get("task") or "Unspecified task"
        reason = item.get("reason") or "No clear test or harness reference."
        referenced_test = item.get("referenced_test")
        issues.append(
            {
                "task_number": task_number,
                "task_title": str(task_title),
                "reason": str(reason),
                "referenced_test": (
                    str(referenced_test) if referenced_test is not None else None
                ),
                "gap_type": item.get("gap_type"),
                "remediation": item.get("remediation"),
                "harness_file": item.get("harness_file"),
                "code_stub": item.get("code_stub"),
            }
        )
    return issues


def _normalise_eval_payload(
    stage_type: str,
    data: dict[str, Any],
    mode: str = "standard",
    *,
    coverage_override: int | None = None,
    use_coverage_override: bool = False,
) -> dict[str, Any]:
    scores = data.get("scores")
    if not isinstance(scores, dict):
        overall_score = _clamp_score(data.get("overall_score"))
        completeness = _clamp_score(data.get("completeness"))
        clarity = _clamp_score(data.get("clarity"))
        coverage_percent = (
            coverage_override
            if use_coverage_override
            else _clamp_score(data.get("coverage_percent"))
        )
        return {
            "overall_score": overall_score,
            "completeness": completeness,
            "clarity": clarity,
            "coverage_percent": coverage_percent,
            "uncovered_reqs": data.get("uncovered_reqs"),
            "tasks_without_ref": _normalise_task_issues(data.get("tasks_without_ref")),
        }

    score_values = {
        key: _clamp_score(value)
        for key, value in scores.items()
        if isinstance(key, str)
    }
    # The harness weights include coverage_percent at 0.20. Feed the DETERMINISTIC
    # value (when the caller supplies one) into the weighted score as well as the
    # stored field, so the judge's truncation-poisoned estimate never reaches the
    # headline score either. A None override means "no coverage data" — the key is
    # left out and _weighted_score renormalises over the remaining weights.
    coverage_percent = (
        coverage_override
        if use_coverage_override
        else _clamp_score(data.get("coverage_percent"))
    )
    if coverage_percent is not None:
        score_values["coverage_percent"] = coverage_percent
    else:
        score_values.pop("coverage_percent", None)

    completeness = _average_score(
        score_values.get("requirements_coverage"),
        score_values.get("user_flow_coverage"),
        score_values.get("non_functional_coverage"),
        score_values.get("traceability"),
    )
    clarity = score_values.get("clarity")
    overall_score = _weighted_score(
        score_values,
        score_weights_for(stage_type, mode),
    )

    uncovered_reqs = data.get("uncovered_reqs")
    if not isinstance(uncovered_reqs, list):
        uncovered_reqs = None

    return {
        "overall_score": overall_score,
        "completeness": completeness,
        "clarity": clarity,
        "coverage_percent": coverage_percent,
        "uncovered_reqs": uncovered_reqs,
        "tasks_without_ref": _normalise_task_issues(data.get("tasks_without_ref")),
    }


def _parse_eval_json(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return data

    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


# Placeholder tokens in _STAGE_PROMPTS, matched against the ORIGINAL template
# only (never against already-substituted text). A chained `.replace().replace()`
# re-scans its own output, so a `spec_content`/`context` value that happens to
# contain the literal substring "{content}" (plausible in ordinary generated
# output — e.g. an API Design section with an example JSON body naming a
# "content" field) gets its second placeholder wrongly re-matched inside the
# just-inserted context block, silently splicing the artifact into the wrong
# slot. `re.sub` with a single compiled alternation walks the template once and
# substitutes via a callback, so inserted values are never rescanned.
_EVAL_PLACEHOLDER_RE = re.compile(r"\{spec_content\}|\{content\}|\{rubric\}")


def _bounded_eval_context(
    stage_type: str,
    spec_content: str,
    context_limit: int,
    *,
    compact: bool,
) -> str:
    """Bound the eval context, per part for tasks (audit H4).

    The tasks context is spec + harness combined; bounding the union let the
    spec consume the head budget and elide nearly the entire harness, so the
    judge graded task→test traceability against a harness it could not see.
    Split on the producer's separator and bound each part with its own budget;
    every other stage keeps the single-bound behaviour.
    """
    if stage_type != "tasks":
        return compact_text(spec_content, context_limit)
    spec_part, harness_part = _split_tasks_eval_context(spec_content)
    if not harness_part:
        return compact_text(spec_content, context_limit)
    spec_limit, harness_limit = _TASKS_CONTEXT_LIMITS[compact]
    return (
        compact_text(spec_part, spec_limit)
        + "\n\n"
        + compact_text(harness_part, harness_limit)
    )


def _build_eval_prompt(
    stage_type: str,
    content: str,
    spec_content: str,
    *,
    compact: bool = False,
    mode: str = "standard",
) -> str:
    context_limit, content_limit = (
        _COMPACT_RETRY_LIMITS if compact else _PROMPT_LIMITS
    ).get(stage_type, _PROMPT_LIMITS["spec"])
    context = _bounded_eval_context(
        stage_type, spec_content, context_limit, compact=compact
    )
    artifact = compact_text(content, content_limit)
    # eval-v3: fence both blocks the way every other judge already does
    # (critic wraps artifact + deps, pr-evaluator wraps diff + criteria) so the
    # INJECTION_DEFENSE_NOTE's nonce protocol in _JUDGE_SYSTEM has real fences
    # to refer to and boundary-spoofing text inside a scored artifact cannot
    # pose as the end of the artifact. Wrapping happens AFTER compaction: the
    # fence nonce is content-bound, so it must cover the exact bytes sent.
    substitutions = {
        "{spec_content}": wrap_untrusted_content("eval_context", context),
        "{content}": wrap_untrusted_content("artifact_under_evaluation", artifact),
        "{rubric}": _rubric_for_stage(stage_type, mode),
    }
    return _EVAL_PLACEHOLDER_RE.sub(
        lambda m: substitutions[m.group()], _stage_prompt_template(stage_type, mode)
    )


async def _call_eval_judge(
    *,
    provider: str,
    model: str,
    user_prompt: str,
) -> str:
    # Count the spend at the point the provider request is issued — once per real
    # attempt, so the compact-prompt re-try counts as the separate call it is
    # (issue #27, Phase 0).
    record_judge_call("eval.score")
    result = await asyncio.wait_for(
        complete_background_llm(
            operation="eval.score",
            provider=provider,
            model=model,
            system=_JUDGE_SYSTEM,
            user=user_prompt,
            max_tokens=output_budget_for_operation("eval.score", provider),
            stage_type="eval",
            prompt_version=EVAL_PROMPT_VERSION,
            adapter_factory=get_llm,
            cost_context=LLMCostContext(product_surface="eval"),
        ),
        timeout=max(settings.llm_complete_timeout_seconds, _EVAL_TIMEOUT_SECONDS),
    )
    return result.output


async def _score_with_retry(
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str,
    model: str,
    mode: str = "standard",
) -> str | None:
    for compact in (False, True):
        user_prompt = _build_eval_prompt(
            stage_type,
            content,
            spec_content,
            compact=compact,
            mode=mode,
        )
        try:
            return await _call_eval_judge(
                provider=provider,
                model=model,
                user_prompt=user_prompt,
            )
        except Exception:
            logger.exception(
                "eval judge call failed for stage_version_id=%s compact=%s",
                stage_version_id,
                compact,
            )
    return None


async def _add_generation_to_dataset(
    *,
    dataset_name: str,
    content_generation_id: str,
    eval_result: EvalResult,
    content: str,
    generation_provider: str | None,
    generation_model: str | None,
) -> None:
    # Denormalize the generation provider/model straight into the dataset item
    # (issue #27 Phase 5) so the high/low_quality datasets are self-contained for
    # model/provider quality comparison — independent of whatever cross-entity
    # querying Langfuse resolves through ``source_observation_id``.  These are the
    # *generation* route's provider/model (the artifact under evaluation), not the
    # judge model.  Omitted when unknown rather than written as null noise.
    item: dict[str, Any] = {
        "stage_type": eval_result.stage_type,
        "overall_score": eval_result.overall_score,
        "completeness": eval_result.completeness,
        "clarity": eval_result.clarity,
        "content": content,
    }
    if generation_provider is not None:
        item["generation_provider"] = generation_provider
    if generation_model is not None:
        item["generation_model"] = generation_model
    await langfuse_service.get_langfuse_client().add_to_dataset(
        dataset_name=dataset_name,
        item=item,
        source_observation_id=content_generation_id,
    )


async def run_eval(
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    db: AsyncSession,
    provider: str = "anthropic",
    judge_model: str | None = None,
    content_generation_id: str | None = None,
    harness_content: str | None = None,
    generation_provider: str | None = None,
    generation_model: str | None = None,
    mode: str = "standard",
) -> EvalResult | None:
    resolved_judge_model = judge_model or JUDGE_MODELS[provider]
    raw = await _score_with_retry(
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        content=content,
        spec_content=spec_content,
        provider=provider,
        model=resolved_judge_model,
        mode=mode,
    )
    if raw is None:
        # Both compact=False and compact=True calls failed — increment the
        # eval poll failure counter so silent drops are visible.  T-194.
        EVAL_POLL_FAILURES.labels(stage_type=stage_type).inc()
        return None

    data = _parse_eval_json(raw)
    if data is None:
        logger.error(
            "eval judge returned non-JSON for stage_version_id=%s: %r",
            stage_version_id,
            raw[:200],
        )
        retry_raw = await _score_with_retry(
            stage_version_id=stage_version_id,
            stage_type=stage_type,
            content=content,
            spec_content=spec_content,
            provider=provider,
            model=resolved_judge_model,
            mode=mode,
        )
        if retry_raw is None:
            EVAL_POLL_FAILURES.labels(stage_type=stage_type).inc()
            return None
        data = _parse_eval_json(retry_raw)
        if data is None:
            logger.error(
                "eval judge retry returned non-JSON for stage_version_id=%s: %r",
                stage_version_id,
                retry_raw[:200],
            )
            EVAL_POLL_FAILURES.labels(stage_type=stage_type).inc()
            return None

    return await _persist_eval_data(
        db,
        data,
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        content=content,
        harness_content=harness_content,
        content_generation_id=content_generation_id,
        generation_provider=generation_provider,
        generation_model=generation_model,
        mode=mode,
    )


def build_eval_request(
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str | None = None,
    mode: str = "standard",
) -> tuple[str, str, int]:
    """Build the (system, user, max_tokens) for one eval-judge call.

    The submit side of the deferred-batch path (Phase 3): a batch request reuses
    exactly the prompt the synchronous path's first (non-compact) attempt would
    send, so a batched eval scores the same artifact identically. ``provider``
    is threaded so a per-(operation, provider) budget override (Phase 4) applies
    to batched evals identically to synchronous ones.
    """
    user_prompt = _build_eval_prompt(
        stage_type, content, spec_content, compact=False, mode=mode
    )
    return (
        _JUDGE_SYSTEM,
        user_prompt,
        output_budget_for_operation("eval.score", provider),
    )


async def persist_eval_from_raw(
    db: AsyncSession,
    raw: str,
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    harness_content: str | None = None,
    content_generation_id: str | None = None,
    generation_provider: str | None = None,
    generation_model: str | None = None,
    mode: str = "standard",
) -> EvalResult | None:
    """Parse a judge response and persist the EvalResult, or return None.

    The completion side of the deferred-batch path: one parse attempt, no
    re-scoring (a batch round trip can take hours — re-batching on a parse miss
    is the wrong call). Returns None when the judge output is not parseable JSON;
    the caller decides whether to fall back to a single synchronous score.
    """
    data = _parse_eval_json(raw)
    if data is None:
        logger.error(
            "batch eval judge returned non-JSON for stage_version_id=%s: %r",
            stage_version_id,
            raw[:200],
        )
        return None
    return await _persist_eval_data(
        db,
        data,
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        content=content,
        harness_content=harness_content,
        content_generation_id=content_generation_id,
        generation_provider=generation_provider,
        generation_model=generation_model,
        mode=mode,
    )


def _deterministic_coverage_percent(harness_content: str) -> int | None:
    """Requirement coverage for a harness, computed from the artifact itself.

    Replaces the judge's ``coverage_percent`` on the harness stage. The judge
    scores a harness compacted to ~20K chars (``_PROMPT_LIMITS["harness"]``, and
    10K on the compact retry) while a real harness runs 60–120KB, so its coverage
    estimate is derived from a fraction of the artifact — the identical
    truncation defect that already disqualified its ``uncovered_reqs`` from both
    the CoveragePanel and the paid patch (D-1). Keeping the judge's number as a
    headline percentage (and weighting it 0.20 in the harness score) meant the
    one figure users read was the least trustworthy signal we produced.

    ``None`` when the matrix names no test files — an unparseable matrix must
    read as "no coverage data" and render nothing, never as 0%.
    """
    covered, total = harness_coverage_ratio(harness_content)
    if total <= 0:
        return None
    return round(100 * covered / total)


async def _persist_eval_data(
    db: AsyncSession,
    data: dict[str, Any],
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    harness_content: str | None,
    content_generation_id: str | None,
    generation_provider: str | None = None,
    generation_model: str | None = None,
    mode: str = "standard",
) -> EvalResult:
    is_harness = stage_type == "harness"
    normalised = _normalise_eval_payload(
        stage_type,
        data,
        mode,
        coverage_override=(
            _deterministic_coverage_percent(content) if is_harness else None
        ),
        use_coverage_override=is_harness,
    )
    coverage_percent: int | None = normalised["coverage_percent"]
    uncovered_reqs: list[str] | None = normalised["uncovered_reqs"]
    tasks_without_ref: list[dict[str, Any]] | None = normalised["tasks_without_ref"]

    # Deterministic task traceability takes precedence over the judge's fallback
    # list whenever harness content is available to validate against.  This is
    # the same helper the inline structural persist and revalidate-tasks use, so
    # all three paths agree (issue #27 Phase 1).
    det_tasks, det_flagged = validate_stage_findings(
        stage_type, content, harness_content
    )
    if det_tasks is not None:
        tasks_without_ref = det_tasks
        flagged = det_flagged
    elif stage_type == "tasks" and tasks_without_ref:
        # No harness to validate against — fall back to the judge's list.
        # GENERATION_FAILURE is a prompt quality issue — only GENUINE_GAP flags.
        flagged = any(
            i.get("gap_type") not in _NON_FLAGGING_GAP_TYPES for i in tasks_without_ref
        )
    else:
        flagged = False
    # Harness `flagged` is deliberately NOT derived from the judge's
    # coverage_percent. The eval compacts the harness to ~20K chars before
    # scoring, so on a normal 60–120KB harness the judge under-counts coverage and
    # would set flagged=True while the deterministic CoveragePanel (matrix→file
    # `deferred_reqs`) shows nothing — a contradictory "Needs attention" badge the
    # user cannot act on (same truncation-poisoned signal we already dropped for
    # uncovered_reqs, D-1). The authoritative harness coverage signal is the
    # deterministic `deferred_reqs`, surfaced directly on the badge/panel.

    # Find-or-update the version's eval row: a sampled judge score updates the
    # row the inline structural persist already created, rather than inserting a
    # racing duplicate (issue #27 Phase 1).
    eval_result = await _get_or_create_eval(db, stage_version_id, stage_type)
    eval_result.stage_type = stage_type
    eval_result.overall_score = normalised["overall_score"]
    eval_result.completeness = normalised["completeness"]
    eval_result.clarity = normalised["clarity"]
    eval_result.coverage_percent = coverage_percent
    eval_result.uncovered_reqs = uncovered_reqs
    eval_result.tasks_without_ref = tasks_without_ref
    eval_result.flagged = flagged
    if stage_type == "tasks" and harness_content:
        eval_result.structural_validator_version = STRUCTURAL_TASK_VALIDATOR_VERSION
    db.add(eval_result)
    await db.commit()
    await db.refresh(eval_result)
    if content_generation_id and eval_result.overall_score is not None:
        try:
            await langfuse_service.get_langfuse_client().score_generation(
                generation_id=content_generation_id,
                name="overall",
                value=float(eval_result.overall_score),
                comment=_score_comment(
                    stage_type, generation_provider, generation_model
                ),
            )
        except Exception:
            logger.exception(
                "eval score link failed for stage_version_id=%s",
                stage_version_id,
            )
        dataset_name = _dataset_for_score(eval_result.overall_score)
        if dataset_name:
            dataset_task = asyncio.create_task(
                _add_generation_to_dataset(
                    dataset_name=dataset_name,
                    content_generation_id=content_generation_id,
                    eval_result=eval_result,
                    content=content,
                    generation_provider=generation_provider,
                    generation_model=generation_model,
                )
            )
            dataset_task.add_done_callback(_log_dataset_error)
    return eval_result


async def run_eval_background(
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str,
    judge_model: str,
    content_generation_id: str | None = None,
    harness_content: str | None = None,
    generation_provider: str | None = None,
    generation_model: str | None = None,
    mode: str = "standard",
) -> EvalResult | None:
    async with AsyncSessionLocal() as db:
        return await run_eval(
            stage_version_id,
            stage_type,
            content,
            spec_content,
            db,
            provider,
            judge_model,
            content_generation_id,
            harness_content=harness_content,
            generation_provider=generation_provider,
            generation_model=generation_model,
            mode=mode,
        )

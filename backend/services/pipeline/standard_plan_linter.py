"""Standard-mode construction verifier — the zero-LLM package linter.

The counterpart to ``demo_day_plan_linter`` for ``mode="standard"`` workspaces.
Pure functions over the four finalised stage contents; **no LLM call**. It earns
(or withholds) the same construction argument Demo Day already had, against
standard mode's much larger section set:

- C1 ``requirement_coverage`` — every upstream ``FR``/``NFR``/``SEC``/``AC`` id is
  named in ≥1 task's ``Spec refs``.
- C2 ``test_coverage`` — every test the harness Requirement-to-Test Matrix names
  is cited by ≥1 task's ``Harness refs``.
- C3 ``dag_acyclic`` — the task ``Dependencies`` graph has no cycle.
- C4 ``plan_coverage`` — every load-bearing plan section is cited by ≥1 task's
  ``Plan refs``.
- C5 ``e2e_reachable`` — the harness declares end-to-end tests and ≥1 task cites
  one, so something in the build actually exercises the product end to end.
- C6 ``task_inventory`` (advisory) — the task count against the spec's distinct
  requirement count.

Why these and not the existing completeness floors: the floors in
``artifact_validator`` are all *advisory* (only ``empty_artifact`` and
``provider_stopped_by_limit`` are refundable, so nothing else can block), and
``_traceability_issues`` only asserts that an id APPEARS SOMEWHERE in TASKS.md —
an ``FR-003`` mentioned once in a traceability table row and implemented by no
task satisfies it. C1 closes that by joining on the ``Spec refs`` field value.
C2 is the forward direction of ``_task_harness_ref_issues``, which only checks
the converse (that the refs a task DOES cite resolve to real harness tests).

**Verdict:** every non-advisory check must pass — but only when ``enforced`` is
True. It ships False: the gaps are computed, persisted and rendered from day one,
while no package flips to red before the standard tasks prompt mandates the
``Plan refs``/``Harness refs`` citations these checks join on (that prompt change
ships in a later, golden-corpus-gated release).

Join-key parity is load-bearing: this module reuses ``artifact_validator``'s
regexes and section/path helpers so it joins on the *exact* tokens the standard
prompts emit and the completeness floors validate. If a token shape changes, both
move together.
"""

from __future__ import annotations

import re

from services.pipeline.artifact_validator import (
    _AC_ID_RE,
    _REQUIREMENT_ID_RE,
    _TASK_DEP_RE,
    _TASK_HEADER_RE,
    _harness_test_refs,
    _normalise_harness_path,
    _ref_matches,
    _section_body,
    _task_dependency_cycle_issues,
)
from services.pipeline.construction_checks import (
    CheckResult,
    ConstructionVerdict,
    field_value,
    plan_coverage_gaps,
    resolve_verified,
)

_BACKTICK_TOKEN_RE = re.compile(r"`([^`]+)`")
_FILE_TOKEN_RE = re.compile(r"\.[A-Za-z0-9]+$")
# The `_(none — <reason>)_` escape marks a setup-only task with no harness test.
_NONE_ESCAPE_RE = re.compile(r"_\(\s*none\b", re.IGNORECASE)

_SPEC_REFS_LABEL = "**Spec refs:**"
_HARNESS_REFS_LABEL = "**Harness refs:**"
_DEPENDENCIES_LABEL = "**Dependencies**"

# The plan sections a shipped product cannot be "working" without, mapped to the
# aliases that count as citing them in a task's `**Plan refs:**`. Deliberately
# generous — the standard tasks prompt's own worked example cites
# "Data Model §subscriptions.state", not the full heading, so exact heading
# matching would mark every real package red (see plan_coverage_gaps).
#
# This is a deliberately SMALL subset of the 24-section standard plan contract:
# only sections whose absence from the build means the product does not run, is
# not reachable, is not secured, or cannot be operated. Design/narrative sections
# (ADRs, Capacity Model, Anti-Patterns…) are not required to have their own task.
_STANDARD_PLAN_COVERAGE: dict[str, tuple[str, ...]] = {
    "## API Design": ("api design", "api", "endpoint"),
    "## Data Model and Persistence": (
        "data model",
        "persistence",
        "schema",
        "migration",
    ),
    "## Authentication and Authorization": (
        "authentication",
        "authorization",
        "auth",
    ),
    "## Security Architecture": ("security architecture", "security"),
    "## Error Handling and Recovery": ("error handling", "recovery"),
    "## Observability and Audit Logging": (
        "observability",
        "audit logging",
        "logging",
        "metrics",
    ),
    "## Deployment and Operations": (
        "deployment and operations",
        "deployment",
        "operations",
        "rollout",
    ),
}


def _task_blocks(tasks_md: str) -> list[tuple[int, str, str]]:
    """Slice TASKS.md into ``(task_id, header, block_text)`` in document order."""
    headers = list(_TASK_HEADER_RE.finditer(tasks_md))
    blocks: list[tuple[int, str, str]] = []
    for i, match in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(tasks_md)
        id_match = _TASK_DEP_RE.search(match.group(0))
        if id_match is None:
            continue
        blocks.append(
            (
                int(id_match.group(1)),
                match.group(0).rstrip(":"),
                tasks_md[match.start() : end],
            )
        )
    return blocks


def _check_requirement_coverage(
    spec_md: str, tasks_md: str, blocks: list[tuple[int, str, str]]
) -> CheckResult:
    """C1: every upstream requirement id is claimed by a task's ``Spec refs``.

    Joins on the FIELD VALUE, not the whole document — that is the entire point.
    An id that appears only in the Traceability Overview table is documented, not
    built.
    """
    upstream = set(_REQUIREMENT_ID_RE.findall(spec_md))
    upstream.update(_AC_ID_RE.findall(spec_md))
    if not upstream:
        return CheckResult(
            "requirement_coverage",
            False,
            ["SPEC.md names no FR/NFR/SEC/AC identifiers to trace"],
        )
    claimed: set[str] = set()
    for _tid, _header, block in blocks:
        value = field_value(block, _SPEC_REFS_LABEL)
        if not value:
            continue
        claimed.update(_REQUIREMENT_ID_RE.findall(value))
        claimed.update(_AC_ID_RE.findall(value))
    missing = sorted(upstream - claimed)
    gaps = [
        f"{req} is not claimed by any task's {_SPEC_REFS_LABEL} — it is specified "
        "but nothing in the build implements it"
        for req in missing[:20]
    ]
    if len(missing) > 20:
        gaps.append(f"…and {len(missing) - 20} further unimplemented requirements")
    return CheckResult("requirement_coverage", not missing, gaps)


def _check_test_coverage(
    harness_md: str, blocks: list[tuple[int, str, str]]
) -> CheckResult:
    """C2: every harness test is made to pass by some task.

    The forward direction of ``_task_harness_ref_issues`` (which only validates
    that the refs a task cites exist). A harness test no task references means a
    tested behaviour that never gets built.
    """
    known = _harness_test_refs(harness_md)
    if not known:
        return CheckResult(
            "test_coverage",
            False,
            ["the HARNESS defines no runnable tests to trace tasks against"],
        )
    # Only compare on bare test-function names: the harness helper emits each test
    # under several key shapes (name, path::name, Class::name, path::Class::name)
    # and a task legitimately cites any one of them.
    bare = {ref for ref in known if "::" not in ref and "/" not in ref}
    cited: set[str] = set()
    for _tid, _header, block in blocks:
        value = field_value(block, _HARNESS_REFS_LABEL)
        if not value or _NONE_ESCAPE_RE.search(value):
            continue
        for token in _BACKTICK_TOKEN_RE.findall(value):
            if not _ref_matches(token, known):
                continue
            cited.add(_normalise_harness_path(token).split("::")[-1])
    missing = sorted(bare - cited)
    gaps = [
        f"harness test `{name}` is referenced by no task's {_HARNESS_REFS_LABEL} — "
        "the behaviour it tests is never built"
        for name in missing[:20]
    ]
    if len(missing) > 20:
        gaps.append(f"…and {len(missing) - 20} further unreferenced harness tests")
    return CheckResult("test_coverage", not missing, gaps)


def _check_dag(blocks: list[tuple[int, str, str]]) -> CheckResult:
    """C3: the task dependency graph is acyclic.

    Standard mode deliberately allows forward references (a model may number
    tasks by feature area), so this reuses the validator's Kahn's-algorithm cycle
    peel rather than Demo Day's stricter "earlier ids only" ordering rule.
    """
    adjacency: dict[int, set[int]] = {}
    for tid, _header, block in blocks:
        value = field_value(block, _DEPENDENCIES_LABEL) or ""
        adjacency[tid] = {int(dep) for dep in _TASK_DEP_RE.findall(value)}
    issues = _task_dependency_cycle_issues(adjacency)
    return CheckResult("dag_acyclic", not issues, [issue.detail for issue in issues])


def _check_plan_coverage(
    plan_md: str, blocks: list[tuple[int, str, str]]
) -> CheckResult:
    """C4: every load-bearing plan section is implemented by some task.

    This is what makes "Deployment and Operations" and "Security Architecture"
    actually mandatory. The standard tasks prompt lists them only as phases that
    "typically" appear, and no validator has ever inspected phases — so a task
    list with nothing that deploys or secures the product passed every gate.
    Checking plan-section citations rather than phase names targets the content,
    not a label the model is free to rename.
    """
    gaps = plan_coverage_gaps(
        plan_md=plan_md,
        task_blocks=blocks,
        required=_STANDARD_PLAN_COVERAGE,
        section_body=_section_body,
    )
    return CheckResult("plan_coverage", not gaps, gaps)


def _looks_like_e2e(token: str) -> bool:
    lowered = token.lower()
    return "e2e" in lowered or "end_to_end" in lowered or "end-to-end" in lowered


def _check_e2e(harness_md: str, blocks: list[tuple[int, str, str]]) -> CheckResult:
    """C5: something in the build exercises the product end to end.

    Standard mode's harness prompt already mandates an E2E tier, but nothing ever
    required a task to land on it — so "working product" reduced to "the unit
    tests pass". Fail-open on shape: when the harness declares no E2E test at all
    this reports the harness gap rather than blaming the task list.
    """
    e2e_tests = {
        ref
        for ref in _harness_test_refs(harness_md)
        if _looks_like_e2e(ref) and "::" not in ref and "/" not in ref
    }
    e2e_files = {
        _normalise_harness_path(token)
        for token in _BACKTICK_TOKEN_RE.findall(harness_md)
        if _FILE_TOKEN_RE.search(token.strip()) and _looks_like_e2e(token)
    }
    if not e2e_tests and not e2e_files:
        return CheckResult(
            "e2e_reachable",
            False,
            [
                "the HARNESS declares no end-to-end test, so no task can prove the "
                "product works end to end"
            ],
        )
    for _tid, _header, block in blocks:
        value = field_value(block, _HARNESS_REFS_LABEL)
        if not value:
            continue
        for token in _BACKTICK_TOKEN_RE.findall(value):
            normalised = _normalise_harness_path(token)
            if _looks_like_e2e(normalised) or normalised in e2e_files:
                return CheckResult("e2e_reachable", True, [])
    return CheckResult(
        "e2e_reachable",
        False,
        [
            "no task's "
            f"{_HARNESS_REFS_LABEL} cites an end-to-end test — nothing in the build "
            "proves the product works end to end"
        ],
    )


def _check_task_inventory(
    spec_md: str, blocks: list[tuple[int, str, str]]
) -> CheckResult:
    """C6 (advisory): is the task list plausibly a real decomposition?

    The standard tasks prompt asks for 20–50 tasks for a non-trivial product while
    the validator floor is 6, so a heavily compressed generation can emit a
    six-task "plan" for a 24-section architecture and draw only a mild advisory.
    Never verdict-bearing: a genuinely small product can be six tasks, and turning
    a heuristic count into a hard failure trains users to ignore the badge.
    """
    count = len(blocks)
    distinct = len(set(_REQUIREMENT_ID_RE.findall(spec_md)))
    if distinct and count < distinct:
        return CheckResult(
            "task_inventory",
            False,
            [
                f"TASKS.md has {count} task blocks for {distinct} distinct "
                "FR/NFR/SEC requirements — a task covering multiple requirements is "
                "usually hiding several slices (advisory — does not affect the "
                "verdict)"
            ],
            advisory=True,
        )
    return CheckResult("task_inventory", True, [], advisory=True)


def verify_construction(
    *,
    spec: str,
    plan: str,
    harness: str,
    tasks: str,
    stage_versions: dict[str, int] | None = None,
    enforced: bool = False,
) -> ConstructionVerdict:
    """Run C1–C6 over the four finalised stage contents and return the verdict.

    ``enforced`` decides whether the non-advisory checks flip ``verified``. It
    defaults to False so the verdict can ship computed-and-visible before the
    prompts that satisfy it land. The flag arrives as a parameter, never a
    settings read, so this module stays pure and trivially unit-testable.

    ``estimated_minutes``/``time_budget_minutes`` are Demo Day's build-time
    calibration and stay None here; the report writer and the frontend already
    guard on non-numeric values.
    """
    blocks = _task_blocks(tasks or "")
    checks = {
        "C1": _check_requirement_coverage(spec or "", tasks or "", blocks),
        "C2": _check_test_coverage(harness or "", blocks),
        "C3": _check_dag(blocks),
        "C4": _check_plan_coverage(plan or "", blocks),
        "C5": _check_e2e(harness or "", blocks),
        "C6": _check_task_inventory(spec or "", blocks),
    }
    return ConstructionVerdict(
        verified=resolve_verified(checks, enforced=enforced),
        checks=checks,
        estimated_minutes=None,
        time_budget_minutes=None,
        stage_versions=dict(stage_versions or {}),
    )

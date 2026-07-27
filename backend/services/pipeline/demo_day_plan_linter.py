"""Demo Day construction verifier — the zero-LLM package linter (plan §7).

For ``mode="demo_day"`` workspaces only. Pure functions over the four finalised
stage contents; **no LLM call**. It earns (or withholds) the construction
guarantee by checking that the package is internally consistent:

- C1 ``dag_acyclic`` — every task's ``Precondition`` refs point only to earlier
  tasks (document order is the topological order, so back-only edges are acyclic).
- C2 ``task_to_test`` — every task's ``Harness refs`` resolve to a harness
  file/test, or use the explicit ``_(none — …)_`` setup-only escape.
- C3 ``ac_to_test`` — every spec ``AC-NNN`` is in the harness Requirement-to-Test
  Matrix **and** referenced by ≥1 task.
- C4 ``e2e_reachable`` — ≥1 e2e test named in the harness End-to-End Smoke Test,
  cited verbatim by the final task's ``Harness refs``.
- C5 ``time_budget`` (advisory) — Σ ``Estimated minutes`` ≤ ``time_budget_minutes``
  (default 300).
- C6 ``plan_coverage`` — every load-bearing plan section (seed data, bootstrap /
  demo surface, external integrations, security architecture) is cited by ≥1
  task's ``Plan refs``. Without this the plan→tasks join was empty: the plan
  could specify the seed command, the run command, the REAL/MOCKED integration
  stances and the auth stance, and the task list could implement none of them
  while the verdict still read ``verified``.
- C7 ``task_inventory`` (advisory) — the task count against the plan's own Build
  Sequence steps and the spec's ``FR-NNN`` count.

**Verdict:** every non-advisory check must pass. C5 and C7 are reported but never
flip the verdict (the §2.2 separation of the two claims). C6 is verdict-bearing
only when ``enforce_plan_coverage`` is passed True — it ships False so the gaps
are visible before any already-green package can turn red (the prompts that
satisfy it land in a later, golden-corpus-gated release).

Join-key parity is load-bearing (plan §7.1.1): this module deliberately reuses
``artifact_validator``'s regexes and section/path helpers so the linter joins on
the *exact* tokens the Demo Day prompts emit and the completeness floors validate.
Importing those private helpers keeps a single source of truth for the join keys —
if the token shape ever changes, both move together.
"""

from __future__ import annotations

import re

from services.pipeline.artifact_validator import (
    _AC_ID_RE,
    _FILE_HEADING_RE,
    _TASK_DEP_RE,
    _TASK_HEADER_RE,
    _file_tree_paths,
    _normalise_harness_path,
    _section_body,
)

# Verdict payload primitives are shared with the standard-mode linter so one
# frontend renderer / report writer / JSONB column serves both modes. Re-exported
# below for the existing import sites (`from ...demo_day_plan_linter import
# ConstructionVerdict`), which must keep working unchanged.
from services.pipeline.construction_checks import (
    STAGE_TYPES,
    CheckResult,
    ConstructionVerdict,
    is_verdict_stale,
    plan_coverage_gaps,
    resolve_verified,
)
from services.pipeline.construction_checks import (
    field_value as _field_value,
)

__all__ = [
    "DEMO_DAY_DEFAULT_BUDGET_MINUTES",
    "STAGE_TYPES",
    "CheckResult",
    "ConstructionVerdict",
    "is_verdict_stale",
    "verify_construction",
]

# The linter's fallback build-time target when the workspace column is NULL. The
# default lives here, not in the DB (plan §7.1.1 / §7.2).
DEMO_DAY_DEFAULT_BUDGET_MINUTES = 300

_BACKTICK_TOKEN_RE = re.compile(r"`([^`]+)`")
_FR_ID_RE = re.compile(r"\bFR-\d{3}\b")
_ESTIMATED_MINUTES_RE = re.compile(r"\*\*Estimated minutes:\*\*\s*([0-9]+)")
# The `_(none — <reason>)_` escape marks a setup-only task with no harness file;
# we only need to detect the opener (em dash or hyphen, any reason).
_NONE_ESCAPE_RE = re.compile(r"_\(\s*none\b", re.IGNORECASE)
# A backticked token names a file when its last path segment carries an extension
# (`tests/e2e/test_smoke.py`, `a/b/c.ts`). Commands like `pytest -q` do not.
_FILE_TOKEN_RE = re.compile(r"\.[A-Za-z0-9]+$")

_PRECONDITION_LABEL = "**Precondition:**"
_HARNESS_REFS_LABEL = "**Harness refs:**"


# The plan sections a Demo Day build cannot be "working" without, mapped to the
# aliases that count as citing them in a task's `**Plan refs:**`. Deliberately
# generous (see construction_checks.plan_coverage_gaps): a false negative would
# mark every real package red and force the check off permanently.
_DEMO_DAY_PLAN_COVERAGE: dict[str, tuple[str, ...]] = {
    # Nothing seeds the demo ⇒ the third run of the demo differs from the first.
    "## Data Model and Persistence": ("data model", "persistence", "schema", "seed"),
    # Nothing makes the app run or deploy ⇒ there is no demo to give.
    "## Environment and Bootstrap": ("environment", "bootstrap", "demo surface"),
    # No task wires the boundary the harness mocks ⇒ the real call never happens.
    "## External Integrations and Secrets": (
        "external integration",
        "integrations and secrets",
        "integration",
        "secrets",
    ),
    # The declared auth stance is designed and never implemented.
    "## Security Architecture": ("security architecture", "security", "auth"),
}

# The plan's own "nothing external is called" escape — the prompt mandates the
# single line "None — <reason>". A build that calls nothing external needs no
# integration task, so requiring one would be a guaranteed false positive.
_PLAN_COVERAGE_NONE_ESCAPES = ("## External Integrations and Secrets",)


# ---------------------------------------------------------------------------
# Parsing helpers (parse-stable on the §7.1.1 token contract).
# ---------------------------------------------------------------------------


def _task_blocks(tasks_md: str) -> list[tuple[int, str, str]]:
    """Slice TASKS.md into ``(task_id, header, block_text)`` in document order.

    Document order *is* the topological order the prompt mandates, so a
    Precondition that names only earlier ids is acyclic by construction (C1).
    """
    headers = list(_TASK_HEADER_RE.finditer(tasks_md))
    blocks: list[tuple[int, str, str]] = []
    for i, match in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(tasks_md)
        block = tasks_md[match.start() : end]
        id_match = _TASK_DEP_RE.search(match.group(0))
        if id_match is None:
            continue
        header = match.group(0).rstrip(":")
        blocks.append((int(id_match.group(1)), header, block))
    return blocks


def _looks_like_file_token(token: str) -> bool:
    return bool(_FILE_TOKEN_RE.search(token.strip()))


def _harness_file_paths(harness_md: str) -> set[str]:
    """The normalised set of files the harness actually contains: every
    ``### File:`` heading plus every ``## File Tree`` leaf, ``harness/``-stripped
    on both sides so task refs and harness paths join."""
    paths = {
        _normalise_harness_path(path) for path in _FILE_HEADING_RE.findall(harness_md)
    }
    tree = _section_body(harness_md, "## File Tree")
    paths.update(_normalise_harness_path(path) for path in _file_tree_paths(tree))
    return {p for p in paths if p}


def _resolves_to_harness_file(
    token: str, harness_paths: set[str], harness_basenames: set[str]
) -> bool:
    normalised = _normalise_harness_path(token)
    if normalised in harness_paths:
        return True
    if any(path.endswith("/" + normalised) for path in harness_paths):
        return True
    # Basename fallback: a task may cite `test_smoke.py` while the tree carries
    # `tests/e2e/test_smoke.py`. Conservative — only flags a genuinely absent file.
    return normalised.rsplit("/", 1)[-1] in harness_basenames


# ---------------------------------------------------------------------------
# The five checks.
# ---------------------------------------------------------------------------


def _check_dag(blocks: list[tuple[int, str, str]]) -> CheckResult:
    gaps: list[str] = []
    index_of = {tid: pos for pos, (tid, _, _) in enumerate(blocks)}
    for pos, (tid, header, block) in enumerate(blocks):
        precondition = _field_value(block, _PRECONDITION_LABEL)
        if precondition is None:
            gaps.append(f"{header}: missing {_PRECONDITION_LABEL} field")
            continue
        for ref in (int(d) for d in _TASK_DEP_RE.findall(precondition)):
            if ref == tid:
                gaps.append(f"{header}: Precondition references itself (T-{ref:03d})")
            elif ref not in index_of:
                gaps.append(
                    f"{header}: Precondition references unknown task T-{ref:03d}"
                )
            elif index_of[ref] >= pos:
                gaps.append(
                    f"{header}: Precondition references T-{ref:03d}, which is not an "
                    "earlier task (would break the acyclic build order)"
                )
    return CheckResult("dag_acyclic", not gaps, gaps)


def _check_task_to_test(
    blocks: list[tuple[int, str, str]], harness_md: str
) -> CheckResult:
    harness_paths = _harness_file_paths(harness_md)
    harness_basenames = {path.rsplit("/", 1)[-1] for path in harness_paths}
    gaps: list[str] = []
    for _tid, header, block in blocks:
        refs_value = _field_value(block, _HARNESS_REFS_LABEL)
        if refs_value is None:
            gaps.append(f"{header}: missing {_HARNESS_REFS_LABEL} field")
            continue
        if _NONE_ESCAPE_RE.search(refs_value):
            # Explicit setup-only exemption — no harness file expected.
            continue
        path_tokens = [
            token
            for token in _BACKTICK_TOKEN_RE.findall(refs_value)
            if _looks_like_file_token(token)
        ]
        if not path_tokens:
            gaps.append(
                f"{header}: Harness refs names no harness file path and uses no "
                "_(none — …)_ escape"
            )
            continue
        for token in path_tokens:
            if not _resolves_to_harness_file(token, harness_paths, harness_basenames):
                gaps.append(
                    f"{header}: Harness ref `{token}` is not present in the harness "
                    "## Files / ## File Tree"
                )
    return CheckResult("task_to_test", not gaps, gaps)


def _check_ac_to_test(spec_md: str, harness_md: str, tasks_md: str) -> CheckResult:
    spec_acs = _ordered_unique(
        _AC_ID_RE.findall(_section_body(spec_md, "## Acceptance Criteria"))
    )
    rtm_acs = set(
        _AC_ID_RE.findall(_section_body(harness_md, "## Requirement-to-Test Matrix"))
    )
    task_acs = set(_AC_ID_RE.findall(tasks_md))
    gaps: list[str] = []
    if not spec_acs:
        gaps.append("SPEC ## Acceptance Criteria names no AC-NNN identifiers")
    for ac in spec_acs:
        if ac not in rtm_acs:
            gaps.append(
                f"{ac} is absent from the harness ## Requirement-to-Test Matrix"
            )
        if ac not in task_acs:
            gaps.append(f"{ac} is not referenced by any task")
    return CheckResult("ac_to_test", not gaps, gaps)


def _check_e2e(harness_md: str, blocks: list[tuple[int, str, str]]) -> CheckResult:
    e2e_body = _section_body(harness_md, "## End-to-End Smoke Test")
    e2e_paths = [
        _normalise_harness_path(token)
        for token in _BACKTICK_TOKEN_RE.findall(e2e_body)
        if _looks_like_file_token(token)
    ]
    if not e2e_paths:
        return CheckResult(
            "e2e_reachable",
            False,
            ["harness ## End-to-End Smoke Test names no concrete test file path"],
        )
    if not blocks:
        return CheckResult(
            "e2e_reachable",
            False,
            ["TASKS.md has no task blocks, so no final task can cite the e2e test"],
        )
    _final_id, final_header, final_block = blocks[-1]
    final_refs = _field_value(final_block, _HARNESS_REFS_LABEL) or ""
    final_tokens = {
        _normalise_harness_path(token)
        for token in _BACKTICK_TOKEN_RE.findall(final_refs)
    }
    final_basenames = {token.rsplit("/", 1)[-1] for token in final_tokens}
    cited = any(
        path in final_tokens or path.rsplit("/", 1)[-1] in final_basenames
        for path in e2e_paths
    )
    if not cited:
        return CheckResult(
            "e2e_reachable",
            False,
            [
                f"the final task ({final_header}) does not cite the e2e smoke test "
                f"path ({', '.join(e2e_paths)}) in its Harness refs"
            ],
        )
    return CheckResult("e2e_reachable", True, [])


def _check_time_budget(
    tasks_md: str, budget_minutes: int
) -> tuple[CheckResult, int | None]:
    minutes = [int(value) for value in _ESTIMATED_MINUTES_RE.findall(tasks_md)]
    total = sum(minutes) if minutes else None
    if total is None:
        return (
            CheckResult(
                "time_budget",
                True,
                ["no per-task **Estimated minutes:** values found (advisory only)"],
                advisory=True,
            ),
            None,
        )
    if total > budget_minutes:
        return (
            CheckResult(
                "time_budget",
                False,
                [
                    f"estimated build time {total} min exceeds the target budget "
                    f"{budget_minutes} min (advisory — does not affect the verdict)"
                ],
                advisory=True,
            ),
            total,
        )
    return CheckResult("time_budget", True, [], advisory=True), total


def _check_plan_coverage(plan_md: str, blocks: list[tuple[int, str, str]]) -> list[str]:
    """C6 gaps: a load-bearing plan section no task implements.

    The plan→tasks join was previously empty — C1–C4 join only on AC ids, harness
    paths, the DAG and the e2e — so the seed command, the demo surface, the
    REAL/MOCKED integration stances and the auth stance could all be specified in
    the plan and dropped by the task list with the verdict still reading
    ``verified``.
    """
    return plan_coverage_gaps(
        plan_md=plan_md,
        task_blocks=blocks,
        required=_DEMO_DAY_PLAN_COVERAGE,
        section_body=_section_body,
        skip_if_body_starts_with_none=_PLAN_COVERAGE_NONE_ESCAPES,
    )


def _check_task_inventory(
    spec_md: str, plan_md: str, blocks: list[tuple[int, str, str]]
) -> CheckResult:
    """C7 (advisory): is the task list plausibly complete for what was specified?

    Purely a signal, never verdict-bearing — a genuinely tiny prototype can be
    four tasks, and turning a heuristic count into a hard failure is exactly the
    kind of false-positive that trains users to ignore the badge. Compares the
    block count against the two things the package itself declares: the plan's own
    Build Sequence steps and the spec's distinct FR count.
    """
    gaps: list[str] = []
    count = len(blocks)
    build_steps = len(
        [
            line
            for line in _section_body(plan_md, "## Build Sequence").splitlines()
            if re.match(r"\s*(?:[-*+]|\d+[.)])\s+\S", line)
        ]
    )
    distinct_fr = len(set(_FR_ID_RE.findall(spec_md)))
    if build_steps and count < build_steps:
        gaps.append(
            f"TASKS.md has {count} task blocks but the plan's ## Build Sequence "
            f"names {build_steps} steps — at least one build step has no task "
            "(advisory — does not affect the verdict)"
        )
    if distinct_fr and count < distinct_fr:
        gaps.append(
            f"TASKS.md has {count} task blocks for {distinct_fr} distinct FR-NNN "
            "requirements — a task covering multiple requirements is usually "
            "hiding several slices (advisory — does not affect the verdict)"
        )
    return CheckResult("task_inventory", not gaps, gaps, advisory=True)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def verify_construction(
    *,
    spec: str,
    plan: str,
    harness: str,
    tasks: str,
    time_budget_minutes: int | None = None,
    stage_versions: dict[str, int] | None = None,
    enforce_plan_coverage: bool = False,
) -> ConstructionVerdict:
    """Run C1–C7 over the four finalised stage contents and return the verdict.

    ``time_budget_minutes`` falls back to ``DEMO_DAY_DEFAULT_BUDGET_MINUTES`` when
    NULL/invalid.

    ``enforce_plan_coverage`` decides whether C6 is verdict-bearing. It defaults
    to False — the check's gaps are computed, persisted and rendered from day one,
    but no already-verified package flips to red until the Demo Day tasks prompt
    mandates the ``Plan refs`` citations C6 looks for (that prompt change ships in
    a later, golden-corpus-gated release). The flag arrives as a parameter, never
    a settings read, so this module stays pure.
    """
    budget = (
        time_budget_minutes
        if isinstance(time_budget_minutes, int) and time_budget_minutes > 0
        else DEMO_DAY_DEFAULT_BUDGET_MINUTES
    )
    blocks = _task_blocks(tasks or "")
    c1 = _check_dag(blocks)
    c2 = _check_task_to_test(blocks, harness or "")
    c3 = _check_ac_to_test(spec or "", harness or "", tasks or "")
    c4 = _check_e2e(harness or "", blocks)
    c5, estimated = _check_time_budget(tasks or "", budget)
    plan_gaps = _check_plan_coverage(plan or "", blocks)
    c6 = CheckResult(
        "plan_coverage",
        not plan_gaps,
        plan_gaps,
        advisory=not enforce_plan_coverage,
    )
    c7 = _check_task_inventory(spec or "", plan or "", blocks)
    checks = {"C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5, "C6": c6, "C7": c7}
    verified = resolve_verified(checks, enforced=True)
    return ConstructionVerdict(
        verified=verified,
        checks=checks,
        estimated_minutes=estimated,
        time_budget_minutes=budget,
        stage_versions=dict(stage_versions or {}),
    )

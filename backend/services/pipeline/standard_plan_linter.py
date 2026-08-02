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
    HarnessTestIndex,
    _canonical_test_path,
    _normalise_harness_ref,
    _section_body,
    _task_dependency_cycle_issues,
    harness_test_index,
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
    "## Frontend Architecture": (
        "frontend architecture",
        "design token",
        "visual identity",
        "frontend",
    ),
}

# ``## Frontend Architecture`` is the one conditional section in this table — a
# backend-only plan legitimately answers it with the prompt-blessed "Not
# applicable because <reason>" one-liner (artifact_validator._CONDITIONAL_SECTIONS),
# so it must not be flagged as an orphaned load-bearing section in that case.
_PLAN_COVERAGE_NONE_ESCAPES = ("## Frontend Architecture",)


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


# Spec sections that DECLINE work. An id whose only mention is here is out of
# scope by construction, so no task should implement it.
_DEFERRAL_SECTIONS = ("## Out of Scope", "## Non-Goals")


def _spec_requirement_ids(spec_md: str) -> set[str]:
    """Every FR/NFR/SEC/AC id the spec commits to building."""

    def ids(text: str) -> set[str]:
        return set(_REQUIREMENT_ID_RE.findall(text)) | set(_AC_ID_RE.findall(text))

    everywhere = ids(spec_md)
    if not everywhere:
        return everywhere
    remainder = spec_md
    declined: set[str] = set()
    for heading in _DEFERRAL_SECTIONS:
        body = _section_body(spec_md, heading)
        if not body:
            continue
        declined |= ids(body)
        remainder = remainder.replace(body, "", 1)
    # Declined only if it appears NOWHERE else — an id mentioned in Out of Scope
    # for contrast ("unlike FR-003, this is deferred") is still in scope.
    return everywhere - (declined - ids(remainder))


def _check_requirement_coverage(
    spec_md: str, tasks_md: str, blocks: list[tuple[int, str, str]]
) -> CheckResult:
    """C1: every upstream requirement id is claimed by a task's ``Spec refs``.

    Joins on the FIELD VALUE, not the whole document — that is the entire point.
    An id that appears only in the Traceability Overview table is documented, not
    built.

    Ids named ONLY under the spec's deferral sections are excluded: "FR-021 is
    deferred to v2" in ## Out of Scope is the spec explicitly declining to build
    something, and demanding a task for it would turn correct scoping into a
    construction gap.
    """
    upstream = _spec_requirement_ids(spec_md)
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


def _ref_tokens(value: str) -> list[str]:
    """The candidate harness references inside one ``**Harness refs:**`` value.

    Backticked tokens are the mandated form and the only ones read when present.
    The un-backticked fallback exists because a model that drops the backticks
    has still named the test — treating that formatting slip as "this test is
    referenced by no task" would manufacture a construction gap out of markdown.
    The fallback is deliberately narrow (path- or ``::``-shaped tokens only) so
    ordinary prose in the field cannot resolve to a test.
    """
    backticked = _BACKTICK_TOKEN_RE.findall(value)
    if backticked:
        return backticked
    return [
        token
        for token in re.split(r"[\s,;]+", value)
        if token and ("::" in token or _FILE_TOKEN_RE.search(token))
    ]


def _cited_tests(
    index: HarnessTestIndex, blocks: list[tuple[int, str, str]]
) -> set[str]:
    """Bare test names some task's ``**Harness refs:**`` actually claims."""
    cited: set[str] = set()
    for _tid, _header, block in blocks:
        value = field_value(block, _HARNESS_REFS_LABEL)
        if not value or _NONE_ESCAPE_RE.search(value):
            continue
        for token in _ref_tokens(value):
            normalised = _normalise_harness_ref(token)
            if "::" in normalised:
                # A qualified ref claims exactly its leaf test — never the rest of
                # the file, or citing one test would silently discharge every
                # sibling test in it.
                leaf = normalised.rsplit("::", 1)[-1]
                if leaf in index.test_names:
                    cited.add(leaf)
                continue
            if normalised in index.test_names:
                cited.add(normalised)
                continue
            # A whole-file ref legitimately claims every test in that file: the
            # task's contract is "this file goes green".
            cited |= index.tests_in_file.get(_canonical_test_path(normalised), set())
    return cited


def _check_test_coverage(
    harness_md: str, blocks: list[tuple[int, str, str]]
) -> CheckResult:
    """C2: every harness test is made to pass by some task.

    The forward direction of ``_task_harness_ref_issues`` (which only validates
    that the refs a task cites exist). A harness test no task references means a
    tested behaviour that never gets built.

    Reads the SHARED multi-language index (``harness_test_index``), not the
    Python-only ``_harness_test_refs``: with the latter a Vitest/Go/RSpec harness
    parsed as zero tests and this check hard-failed every non-Python package on a
    parser limitation rather than a construction gap.

    When the harness carries real code the scanner cannot name tests in, the
    honest answer is "unverified", not "failed" — this check reports the
    limitation and passes, mirroring ``online_eval``'s UNVERIFIED_COVERAGE class.
    A hard fail is reserved for the two cases that are genuinely the package's
    fault: no harness files at all, or files we parse completely that define no
    test.
    """
    index = harness_test_index(harness_md)
    if not index.test_names:
        blind = index.unparsed_test_files()
        if blind:
            return CheckResult(
                "test_coverage",
                True,
                [
                    "harness tests could not be parsed for "
                    f"{', '.join(f'`{path}`' for path in sorted(blind)[:5])} — "
                    "task-to-test coverage is unverified for this stack, not "
                    "failed"
                ],
            )
        if not index.known_files:
            return CheckResult(
                "test_coverage",
                False,
                ["the HARNESS defines no runnable tests to trace tasks against"],
            )
        return CheckResult(
            "test_coverage",
            False,
            [
                "the HARNESS names files but none of them defines a runnable test, "
                "so no task can be traced to a verification"
            ],
        )
    missing = sorted(index.test_names - _cited_tests(index, blocks))
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
        skip_if_body_starts_with_none=_PLAN_COVERAGE_NONE_ESCAPES,
    )
    return CheckResult("plan_coverage", not gaps, gaps)


# What the Requirement-to-Test Matrix's `test type` cell (or a test/file name)
# has to say for a row to count as end-to-end evidence. Naming alone is NOT
# sufficient as a join key: the standard harness prompt names `e2e` exactly once,
# inside a *recommended* directory layout, and never mandates the convention — so
# a compliant harness whose journey test is `tests/integration/test_signup_flow.py`
# with an `e2e` type cell has to resolve, or the check fails on a filename style.
_E2E_MARKERS = ("e2e", "end_to_end", "end-to-end", "end to end", "smoke", "journey")


def _looks_like_e2e(token: str) -> bool:
    lowered = token.lower()
    return any(marker in lowered for marker in _E2E_MARKERS)


def _matrix_e2e_refs(harness_md: str) -> set[str]:
    """Normalised file/test tokens from Requirement-to-Test Matrix rows whose own
    cells declare the row end-to-end."""
    body = _section_body(harness_md, "## Requirement-to-Test Matrix")
    refs: set[str] = set()
    for line in body.splitlines():
        if "|" not in line or not _looks_like_e2e(line):
            continue
        for token in _BACKTICK_TOKEN_RE.findall(line):
            normalised = _normalise_harness_ref(token)
            if "::" in normalised or _FILE_TOKEN_RE.search(normalised):
                refs.add(normalised)
    return refs


def _check_e2e(harness_md: str, blocks: list[tuple[int, str, str]]) -> CheckResult:
    """C5: something in the build exercises the product end to end.

    Standard mode's harness prompt already mandates an E2E tier, but nothing ever
    required a task to land on it — so "working product" reduced to "the unit
    tests pass". Fail-open on shape: when the harness declares no E2E test at all
    this reports the harness gap rather than blaming the task list.

    Evidence is drawn from the test/file NAMES *and* from the matrix rows that
    declare themselves end-to-end, so a compliant harness that simply does not
    use the word "e2e" in a filename still resolves.
    """
    index = harness_test_index(harness_md)
    e2e_tests = {name for name in index.test_names if _looks_like_e2e(name)}
    e2e_files = {path for path in index.known_files if _looks_like_e2e(path)}
    matrix_refs = _matrix_e2e_refs(harness_md)
    for ref in matrix_refs:
        head, _, leaf = ref.rpartition("::")
        if leaf in index.test_names:
            e2e_tests.add(leaf)
        path = _canonical_test_path(head or ref)
        if path in index.known_files:
            e2e_files.add(path)
            e2e_tests.update(index.tests_in_file.get(path, set()))
    if not e2e_tests and not e2e_files and not matrix_refs:
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
        if not value or _NONE_ESCAPE_RE.search(value):
            continue
        for token in _ref_tokens(value):
            normalised = _normalise_harness_ref(token)
            if _looks_like_e2e(normalised) or normalised in matrix_refs:
                return CheckResult("e2e_reachable", True, [])
            leaf = normalised.rsplit("::", 1)[-1]
            if leaf in e2e_tests:
                return CheckResult("e2e_reachable", True, [])
            head = normalised.split("::", 1)[0]
            if _canonical_test_path(head) in e2e_files:
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
    # Same in-scope id set C1 uses, so a spec that defers FR-021 in ## Out of
    # Scope is not also counted against the task list here.
    distinct = len(
        {req for req in _spec_requirement_ids(spec_md) if _REQUIREMENT_ID_RE.match(req)}
    )
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

    ``enforced`` decides whether C1–C5 are verdict-bearing. It defaults to False
    so the verdict can ship computed-and-visible before the prompts that satisfy
    it land. The flag arrives as a parameter, never a settings read, so this
    module stays pure and trivially unit-testable.

    While un-enforced the checks carry ``enforced=False`` IN THE PAYLOAD rather
    than having the verdict overridden by a blanket ``verified=True`` computed
    behind them. Same shape Demo Day uses, one definition across both modes, and
    it keeps the gaps honest: an un-enforced failure is still a real structural
    gap and is still named by the report and the badge — it just cannot withhold
    ``verified``. (Marking them ``advisory`` instead would demote a genuine
    failure to a calibration note and make the report print
    "✅ Construction-verified" over a list of FAILs.)

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
    for check_id in ("C1", "C2", "C3", "C4", "C5"):
        checks[check_id].enforced = enforced
    return ConstructionVerdict(
        verified=resolve_verified(checks),
        checks=checks,
        estimated_minutes=None,
        time_budget_minutes=None,
        stage_versions=dict(stage_versions or {}),
    )

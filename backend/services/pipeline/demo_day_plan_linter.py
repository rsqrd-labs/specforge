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

**Verdict:** ``verified = C1 and C2 and C3 and C4``. C5 is reported but never
flips the verdict (the §2.2 separation of the two claims).

Join-key parity is load-bearing (plan §7.1.1): this module deliberately reuses
``artifact_validator``'s regexes and section/path helpers so the linter joins on
the *exact* tokens the Demo Day prompts emit and the completeness floors validate.
Importing those private helpers keeps a single source of truth for the join keys —
if the token shape ever changes, both move together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.pipeline.artifact_validator import (
    _AC_ID_RE,
    _FILE_HEADING_RE,
    _TASK_DEP_RE,
    _TASK_HEADER_RE,
    _file_tree_paths,
    _normalise_harness_path,
    _section_body,
)

# The linter's fallback build-time target when the workspace column is NULL. The
# default lives here, not in the DB (plan §7.1.1 / §7.2).
DEMO_DAY_DEFAULT_BUDGET_MINUTES = 300

# The four stage types the verdict spans, in pipeline order. The verdict stamps a
# version per type; a mismatch against the live versions is the staleness signal.
STAGE_TYPES = ("spec", "plan", "harness", "tasks")

_BACKTICK_TOKEN_RE = re.compile(r"`([^`]+)`")
_ESTIMATED_MINUTES_RE = re.compile(r"\*\*Estimated minutes:\*\*\s*([0-9]+)")
# The `_(none — <reason>)_` escape marks a setup-only task with no harness file;
# we only need to detect the opener (em dash or hyphen, any reason).
_NONE_ESCAPE_RE = re.compile(r"_\(\s*none\b", re.IGNORECASE)
# A backticked token names a file when its last path segment carries an extension
# (`tests/e2e/test_smoke.py`, `a/b/c.ts`). Commands like `pytest -q` do not.
_FILE_TOKEN_RE = re.compile(r"\.[A-Za-z0-9]+$")

_PRECONDITION_LABEL = "**Precondition:**"
_HARNESS_REFS_LABEL = "**Harness refs:**"


@dataclass
class CheckResult:
    """One construction check's outcome: pass/fail plus the specific gaps."""

    name: str
    passed: bool
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "gaps": list(self.gaps)}


@dataclass
class ConstructionVerdict:
    """The §7.2 verdict. ``to_dict`` is the persisted JSONB shape that
    ``agent_manual_service.build_construction_report`` renders and the
    ``construction_verdict`` workspace column stores."""

    verified: bool
    checks: dict[str, CheckResult]
    # None — not 0 — when no per-task estimate parsed, so the report can say
    # "no estimates available" rather than implying a 0-minute build.
    estimated_minutes: int | None
    time_budget_minutes: int
    stage_versions: dict[str, int] = field(default_factory=dict)
    # Idempotency marker for the one platform-funded advisory regenerate (§7.3).
    # Set once a funded regen has been attempted for this workspace so it never
    # fires twice. Persisted inside the verdict JSON (no extra column).
    regen_attempted: bool = False

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "checks": {cid: c.to_dict() for cid, c in self.checks.items()},
            "estimated_minutes": self.estimated_minutes,
            "time_budget_minutes": self.time_budget_minutes,
            "stage_versions": dict(self.stage_versions),
            "regen_attempted": self.regen_attempted,
        }


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


def _field_value(block: str, label: str) -> str | None:
    """Return the value following ``label`` (a ``**Field:**`` marker), or None if
    the field is absent. Captures up to the next bold field, heading, or blank
    line so a value that wraps onto an indented continuation line is preserved."""
    idx = block.find(label)
    if idx == -1:
        return None
    rest = block[idx + len(label) :]
    stop = len(rest)
    for pattern in (r"\n\s*\*\*[A-Za-z]", r"\n#{2,3}\s", r"\n\s*\n"):
        match = re.search(pattern, rest)
        if match is not None:
            stop = min(stop, match.start())
    return rest[:stop].strip()


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
            ),
            total,
        )
    return CheckResult("time_budget", True, []), total


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def is_verdict_stale(verdict: dict | None, current_versions: dict[str, int]) -> bool:
    """True when a persisted verdict was computed against older stage versions.

    The verifier can only run once all four stages exist, but any stage can be
    regenerated/refined afterward (plan §9.2). The verdict stamps each stage's
    version; if any live version differs from the stamped one, the verdict is
    stale and must be recomputed before it is trusted (on export, in the UI). A
    missing/empty verdict is treated as stale so the first computation always
    runs. A version absent from either side is treated as a mismatch (conservative
    — recompute rather than serve a verdict that may not match the live package).
    """
    if not verdict:
        return True
    stamped = verdict.get("stage_versions") or {}
    return any(
        stamped.get(stage_type) != current_versions.get(stage_type)
        for stage_type in STAGE_TYPES
    )


def verify_construction(
    *,
    spec: str,
    plan: str,
    harness: str,
    tasks: str,
    time_budget_minutes: int | None = None,
    stage_versions: dict[str, int] | None = None,
) -> ConstructionVerdict:
    """Run C1–C5 over the four finalised stage contents and return the verdict.

    ``plan`` is accepted for a uniform four-stage call site (and future checks);
    C1–C5 currently join only spec/harness/tasks. ``time_budget_minutes`` falls
    back to ``DEMO_DAY_DEFAULT_BUDGET_MINUTES`` when NULL/invalid.
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
    checks = {"C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5}
    verified = c1.passed and c2.passed and c3.passed and c4.passed
    return ConstructionVerdict(
        verified=verified,
        checks=checks,
        estimated_minutes=estimated,
        time_budget_minutes=budget,
        stage_versions=dict(stage_versions or {}),
    )

"""Shared construction-verifier primitives (both modes).

The Demo Day construction verifier (``demo_day_plan_linter``) and the standard
one (``standard_plan_linter``) answer the same question — *if every task is
implemented, do you get a working thing?* — against different section sets. They
share the verdict payload shape so ONE frontend renderer, ONE persisted JSONB
column (``workspaces.construction_verdict``), and ONE report writer
(``agent_manual_service.build_construction_report``) serve both.

This module holds only what both need: the two dataclasses and the plan-section
→ task ``**Plan refs:**`` coverage join. It stays pure — no config, no ORM, no
settings import — so the linters that build on it remain trivially unit-testable
and safe to run on the CPU-offload pool. Feature flags reach the linters as
function parameters, never as a module-level read.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

# The four stage types a verdict spans, in pipeline order.
STAGE_TYPES = ("spec", "plan", "harness", "tasks")


@dataclass
class CheckResult:
    """One construction check's outcome: pass/fail plus the specific gaps.

    ``advisory`` is the load-bearing addition: it travels IN the payload so the
    frontend no longer has to hardcode which check ids flip the verdict. The two
    modes have different check sets, and a hardcoded id list silently swallows
    any check added later (that was the pre-existing coupling in
    ``constructionVerdict.ts``). An advisory check is computed, persisted, and
    rendered, but never affects ``ConstructionVerdict.verified``.

    ``enforced`` is a SECOND, orthogonal axis, and the distinction matters:

    * ``advisory=True`` — never verdict-bearing *by nature*. The build-time
      budget and the task-count heuristic are calibration signals; a genuinely
      small product can fail them while being perfectly well constructed, so
      they must never be counted as gaps anywhere.
    * ``enforced=False`` — verdict-bearing in principle, but its rollout flag is
      still off. The gap is REAL and is named everywhere a gap is named (report,
      badge); it just cannot withhold ``verified`` yet.

    Collapsing the second into the first (which is what ``advisory=not enforced``
    did) makes a real structural failure indistinguishable from a calibration
    note, and the report then prints "✅ Construction-verified" above a list of
    FAILs — the exact overclaim the verdict exists to prevent.
    """

    name: str
    passed: bool
    gaps: list[str] = field(default_factory=list)
    advisory: bool = False
    enforced: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "gaps": list(self.gaps),
            "advisory": self.advisory,
            "enforced": self.enforced,
        }


@dataclass
class ConstructionVerdict:
    """The persisted verdict. ``to_dict`` is the JSONB shape stored on
    ``workspaces.construction_verdict``, rendered by
    ``agent_manual_service.build_construction_report`` and by the frontend
    ``ConstructionVerifiedBadge``.

    ``time_budget_minutes``/``estimated_minutes`` are Demo Day's advisory
    build-time calibration; standard mode leaves both ``None`` (the report writer
    and the handoff panel already guard on non-numeric values, so a ``None``
    budget renders as "no estimate available" rather than a 0h build).
    """

    verified: bool
    checks: dict[str, CheckResult]
    estimated_minutes: int | None
    time_budget_minutes: int | None
    stage_versions: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "checks": {cid: c.to_dict() for cid, c in self.checks.items()},
            "estimated_minutes": self.estimated_minutes,
            "time_budget_minutes": self.time_budget_minutes,
            "stage_versions": dict(self.stage_versions),
        }


def resolve_verified(checks: dict[str, CheckResult]) -> bool:
    """``verified`` = every check that is both non-advisory AND enforced passed.

    The un-enforced mode is how a new check ships: the gaps are computed,
    persisted, and named in the report and the UI from day one, but they cannot
    withhold the verdict flag before the prompts that satisfy them have landed
    and been measured. Note what this does NOT do — it does not hide the gaps.
    Both renderers report what the checks found; ``verified`` is the narrower
    claim "no enforced check withheld the guarantee".
    """
    return all(
        check.passed
        for check in checks.values()
        if not check.advisory and check.enforced
    )


def is_verdict_stale(verdict: dict | None, current_versions: dict[str, int]) -> bool:
    """True when a persisted verdict was computed against older stage versions.

    The verifier can only run once all four stages exist, but any stage can be
    regenerated/refined afterward. The verdict stamps each stage's version; if any
    live version differs from the stamped one the verdict is stale and must be
    recomputed before it is trusted (on export, in the UI). A missing/empty
    verdict is treated as stale so the first computation always runs. A version
    absent from either side counts as a mismatch (conservative — recompute rather
    than serve a verdict that may not match the live package).
    """
    if not verdict:
        return True
    stamped = verdict.get("stage_versions") or {}
    return any(
        stamped.get(stage_type) != current_versions.get(stage_type)
        for stage_type in STAGE_TYPES
    )


# ---------------------------------------------------------------------------
# Plan-section → task coverage (the plan→tasks join both modes were missing).
# ---------------------------------------------------------------------------

# Strip markdown emphasis/among punctuation so `**Plan refs:**` values written as
# "Data Model §subscriptions.state", "`## Security Architecture`", or
# "Security Architecture (auth)" all normalise to comparable text.
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


def normalise_reference(text: str) -> str:
    """Lowercase, punctuation-collapsed form used for all coverage matching."""
    return _NORMALISE_RE.sub(" ", text.lower()).strip()


def field_value(block: str, label: str) -> str | None:
    """Return the value following ``label`` (a ``**Field:**`` marker), or None if
    the field is absent.

    Captures up to the next bold field, heading, or blank line so a value that
    wraps onto an indented continuation line is preserved.
    """
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


PLAN_REFS_LABEL = "**Plan refs:**"


def plan_coverage_gaps(
    *,
    plan_md: str,
    task_blocks: Sequence[tuple[int, str, str]],
    required: dict[str, tuple[str, ...]],
    section_body: Callable[[str, str], str],
    skip_if_body_starts_with_none: Iterable[str] = (),
) -> list[str]:
    """Gaps where a load-bearing plan section is implemented by no task.

    ``required`` maps each plan heading to the aliases that count as citing it in
    a task's ``**Plan refs:**``. Aliases are deliberately GENEROUS: a false
    negative here would mark every real package red and force the check to be
    disabled permanently, whereas a false positive merely fails to flag one
    genuinely-orphaned section. The standard prompt's own worked example cites
    "Data Model §subscriptions.state" rather than the full heading, so exact
    heading matching is not an option.

    ``section_body`` is injected (rather than imported) so each linter passes the
    same ``artifact_validator._section_body`` it uses everywhere else — join-key
    parity with the validator is load-bearing, and importing it here would make
    this module depend on the validator for one call.

    Guards, in order:
    - A section ABSENT from the plan is skipped. Its absence is already a
      terminal ``MissingSectionError`` from ``validate_sections``; reporting it
      again here would double-charge the user for one defect.
    - A section listed in ``skip_if_body_starts_with_none`` whose body opens with
      "None" is skipped — that is the prompt's explicit "nothing to build here"
      escape (e.g. a plan that calls no external service).
    - Only the ``**Plan refs:**`` FIELD VALUE is searched, never Steps or
      Description prose, so a task that merely mentions "the data model" in a
      sentence does not count as implementing it.
    """
    # Padded so containment is a WORD-boundary test: the normalised form is
    # lowercase words joined by single spaces, so `" api " in " rapid api "`
    # matches the real citation while `" api " in " rapids "` does not. Bare
    # substring matching let short aliases ("api", "auth", "schema") resolve
    # inside unrelated words and silently discharge a section no task implements.
    cited: list[str] = []
    for _tid, _header, block in task_blocks:
        value = field_value(block, PLAN_REFS_LABEL)
        if value:
            cited.append(f" {normalise_reference(value)} ")

    skip_none = {heading for heading in skip_if_body_starts_with_none}
    gaps: list[str] = []
    for heading, aliases in required.items():
        body = section_body(plan_md, heading)
        if not body.strip():
            # Absent (or empty) in the plan — validate_sections owns this.
            continue
        if heading in skip_none and normalise_reference(body).startswith("none"):
            continue
        needles = tuple(
            f" {normalised} "
            for alias in aliases
            if (normalised := normalise_reference(alias))
        )
        if any(needle in value for value in cited for needle in needles):
            continue
        gaps.append(
            f"no task's {PLAN_REFS_LABEL} cites `{heading}` — the plan specifies "
            "it but nothing in the build implements it"
        )
    return gaps

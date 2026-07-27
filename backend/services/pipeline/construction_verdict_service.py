"""Construction-verdict orchestration over the persisted stages (both modes).

A thin DB-aware layer over the pure, zero-LLM linters — Demo Day's
(:mod:`services.pipeline.demo_day_plan_linter`) and standard mode's
(:mod:`services.pipeline.standard_plan_linter`). It reads the four stage
contents/versions off the workspace, dispatches on ``workspace.mode``, and
persists the verdict to ``workspaces.construction_verdict``.

Kept separate from the linters (which stay pure / ORM-free / settings-free so
they are trivially unit-testable and safe on the CPU-offload pool) and from
``stage_manager`` (so ``export_service`` can reuse the export-time staleness
re-run without importing the whole generation pipeline — avoiding an import
cycle). This module is the ONLY place ``settings`` is read on the verdict path;
the enforcement flags are passed down as parameters.

Verification is advisory-only end to end: it never blocks a generation, never
invokes the generation machinery, and never fails an export.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import Stage, Workspace
from services.pipeline import standard_plan_linter
from services.pipeline.construction_checks import (
    STAGE_TYPES,
    ConstructionVerdict,
    is_verdict_stale,
)
from services.pipeline.demo_day_plan_linter import verify_construction

logger = logging.getLogger(__name__)


def current_versions(stages: dict[str, Stage]) -> dict[str, int]:
    """The live ``{stage_type: current_version}`` map the verdict stamps."""
    return {
        stage_type: int(stages[stage_type].current_version)
        for stage_type in STAGE_TYPES
        if stages.get(stage_type) is not None
    }


def all_stages_present(stages: dict[str, Stage]) -> bool:
    """True only when every one of the four stages exists with non-empty content.

    The verifier joins across all four artifacts, so a missing/empty stage makes
    every check vacuously fail — guard against running it before the package is
    whole (it runs after the tasks stage, by which point spec/plan/harness are
    finalised, but a defensive caller may invoke it earlier).
    """
    return all(
        stages.get(stage_type) is not None and bool(stages[stage_type].content)
        for stage_type in STAGE_TYPES
    )


def compute_verdict(
    workspace: Workspace,
    stages: dict[str, Stage],
) -> ConstructionVerdict:
    """Run the mode-appropriate zero-LLM linter over the four stage contents.

    Both linters return the same ``ConstructionVerdict`` shape, so one persisted
    column, one report writer, and one frontend renderer serve both modes. The
    enforcement flags are read here (the linters stay settings-free) and decide
    only whether a check may flip ``verified`` — every check runs and reports its
    gaps either way.
    """
    contents = {
        stage_type: (stages[stage_type].content or "") for stage_type in STAGE_TYPES
    }
    versions = current_versions(stages)
    if getattr(workspace, "mode", "standard") == "demo_day":
        return verify_construction(
            **contents,
            time_budget_minutes=workspace.time_budget_minutes,
            stage_versions=versions,
            enforce_plan_coverage=settings.demo_day_plan_coverage_enforced,
        )
    return standard_plan_linter.verify_construction(
        **contents,
        stage_versions=versions,
        enforced=settings.standard_construction_verifier_enforced,
    )


async def compute_verdict_async(
    workspace: Workspace,
    stages: dict[str, Stage],
) -> ConstructionVerdict:
    """Async ``compute_verdict``: offloads the linter off the event loop (F7).

    ``verify_construction`` cross-joins regex/line passes over ALL FOUR full
    stage documents — the largest combined CPU payload on the pipeline — so on
    the post-tasks verifier and the export staleness re-run it is dispatched to
    the dedicated CPU pool (sized by the combined artifact length; small
    packages run inline). Result object is identical to ``compute_verdict``.

    The offload matters MORE for standard mode than for Demo Day: a standard
    package carries a 24-section plan and a full harness, several times the
    combined bytes of a lean ≤5-hour one.
    """
    from services.cpu_offload import run_cpu_bound

    sizer = "".join(
        stages[stage_type].content or ""
        for stage_type in STAGE_TYPES
        if stages.get(stage_type) is not None
    )
    return await run_cpu_bound(sizer, compute_verdict, workspace, stages)


async def ensure_fresh_verdict(
    db: AsyncSession,
    workspace: Workspace,
    stages: dict[str, Stage],
) -> dict | None:
    """Return a verdict that matches the live stage versions, recomputing if stale.

    The export-time staleness re-run (plan §7.3 / §9.2): a verdict computed after
    the tasks stage can go stale if any stage is refined afterward. The linter is
    zero-LLM and cheap, so on export we recompute synchronously when stale and
    persist the fresh verdict before rendering ``CONSTRUCTION_REPORT.md``.

    Fully best-effort: this runs on a read/export path and must never fail a
    download. Any error (or an incomplete package) falls back to the persisted
    verdict (possibly ``None``). A stale re-run only refreshes the structural
    verdict and never triggers an LLM call.

    Runs for BOTH modes. Note that this deliberately recomputes only when the
    stamped stage versions no longer match the live ones — a verdict persisted
    before a new check existed keeps its old value until the package actually
    changes. There is no backfill: silently turning already-verified packages red
    with no user action would be worse than a stale-but-honest verdict.
    """
    existing = getattr(workspace, "construction_verdict", None)
    if not all_stages_present(stages):
        return existing
    try:
        if not is_verdict_stale(existing, current_versions(stages)):
            return existing
        verdict = await compute_verdict_async(workspace, stages)
        workspace.construction_verdict = verdict.to_dict()
        await db.commit()
        return workspace.construction_verdict
    except Exception:
        logger.warning(
            "construction_verdict_service.refresh_failed workspace_id=%s",
            getattr(workspace, "id", None),
            exc_info=True,
        )
        # Leave the session usable for the rest of the export.
        try:
            await db.rollback()
        except Exception:  # pragma: no cover - best-effort rollback
            logger.exception("construction_verdict_service.refresh_rollback_failed")
        return existing

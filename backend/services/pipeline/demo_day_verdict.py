"""Demo Day construction-verdict orchestration over the persisted stages.

A thin DB-aware layer over the pure, zero-LLM linter
(:mod:`services.pipeline.demo_day_plan_linter`): it reads the four stage
contents/versions off the workspace, runs ``verify_construction``, and persists
the verdict to ``workspaces.construction_verdict`` (plan §7.2).

Kept separate from the linter (which stays pure / ORM-free so it is trivially
unit-testable) and from ``stage_manager`` (so ``export_service`` can reuse the
export-time staleness re-run without importing the whole generation pipeline —
avoiding an import cycle). Verification is advisory-only and never invokes the
generation machinery.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models import Stage, Workspace
from services.pipeline.demo_day_plan_linter import (
    STAGE_TYPES,
    ConstructionVerdict,
    is_verdict_stale,
    verify_construction,
)

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
    """Run the zero-LLM linter over the workspace's four stage contents."""
    return verify_construction(
        spec=stages["spec"].content or "",
        plan=stages["plan"].content or "",
        harness=stages["harness"].content or "",
        tasks=stages["tasks"].content or "",
        time_budget_minutes=workspace.time_budget_minutes,
        stage_versions=current_versions(stages),
    )


async def compute_verdict_async(
    workspace: Workspace,
    stages: dict[str, Stage],
) -> ConstructionVerdict:
    """Async ``compute_verdict``: offloads the linter off the event loop (F7).

    ``verify_construction`` cross-joins regex/line passes over ALL FOUR full
    stage documents — the largest combined CPU payload on the pipeline — so on
    the demo-day verifier and the export staleness re-run it is dispatched to
    the dedicated CPU pool (sized by the combined artifact length; small
    packages run inline). Result object is identical to ``compute_verdict``.
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
    """
    if getattr(workspace, "mode", "standard") != "demo_day":
        return None
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
            "demo_day_verdict.refresh_failed workspace_id=%s",
            getattr(workspace, "id", None),
            exc_info=True,
        )
        # Leave the session usable for the rest of the export.
        try:
            await db.rollback()
        except Exception:  # pragma: no cover - best-effort rollback
            logger.exception("demo_day_verdict.refresh_rollback_failed")
        return existing

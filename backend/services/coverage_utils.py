"""Coverage derivation utilities — shared across workspace, PDF, and public share.

Batch query for N workspaces issues exactly one SQL round-trip using a
WHERE … IN (workspace_ids) clause, keeping the workspace-list endpoint at
O(1) DB queries regardless of how many workspaces the user has.

HF-1 — T-198 (batch N+1 fix).
MF-2 — T-206 (shared utility; removes cross-module private import).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import EvalResult, Stage, StageVersion
from schemas.workspace import CoverageSummary

logger = logging.getLogger(__name__)

# Hard upper bound on the IN-clause width.  PostgreSQL handles large IN
# clauses well, but > 500 is unusual in production and signals a missing
# pagination limit at the API layer.  Callers that page workspaces at ≤ 500
# per page will never hit this cap under normal operation.
_MAX_BATCH_SIZE = 500


async def derive_coverage_summaries(
    workspace_ids: list[UUID],
    db: AsyncSession,
) -> dict[UUID, CoverageSummary | None]:
    """Return coverage summaries for all workspace IDs in a single SQL query.

    Issues exactly one ``SELECT … WHERE stage.workspace_id IN (workspace_ids)``
    round-trip, making the workspace-list endpoint O(1) DB queries regardless
    of workspace count.  Returns ``None`` for workspaces with no harness stage
    or no completed eval result.

    Args:
        workspace_ids: List of workspace UUIDs to query.  Capped at
            _MAX_BATCH_SIZE entries; callers should paginate at the API layer.
        db: The async SQLAlchemy session.

    Returns:
        A ``dict`` mapping every supplied workspace_id to its
        :class:`~schemas.workspace.CoverageSummary` or ``None``.
    """
    if not workspace_ids:
        # Short-circuit: avoid emitting an IN () with an empty list.
        return {}

    # Enforce the hard cap to prevent unbounded IN clauses.
    ids_to_query = workspace_ids[:_MAX_BATCH_SIZE]
    if len(workspace_ids) > _MAX_BATCH_SIZE:
        logger.warning(
            "coverage_utils.batch_cap_exceeded",
            extra={
                "requested": len(workspace_ids),
                "capped_at": _MAX_BATCH_SIZE,
            },
        )

    # Single batched query — fetch all matching rows ordered most-recent first.
    # Python de-duplication (take first row per workspace_id) is O(n) in the
    # number of eval results, which is bounded and avoids a DISTINCT ON subquery.
    rows = await db.execute(
        select(Stage.workspace_id, EvalResult.coverage_percent)
        .join(StageVersion, EvalResult.stage_version_id == StageVersion.id)
        .join(Stage, StageVersion.stage_id == Stage.id)
        .where(
            Stage.workspace_id.in_(ids_to_query),
            Stage.type == "harness",
            EvalResult.coverage_percent.is_not(None),
        )
        .order_by(EvalResult.created_at.desc())
    )

    # Initialise every requested workspace_id to None (not yet covered).
    result: dict[UUID, CoverageSummary | None] = {wid: None for wid in workspace_ids}

    # Iterate the result set and keep only the first (most-recent) row per workspace.
    seen: set[UUID] = set()
    for workspace_id, pct in rows:
        if workspace_id in seen:
            continue  # already have the most-recent eval for this workspace
        seen.add(workspace_id)
        pct_int = max(0, min(100, int(pct)))
        # `percent` is authoritative and is now DETERMINISTIC: since the coverage
        # rework it is `harness_coverage_ratio` (matrix requirements whose mapped
        # test file was actually emitted), not the eval judge's estimate — the
        # judge only ever saw ~20K chars of a 60–120KB harness, so its number was
        # the least reliable figure we displayed.
        #
        # `tests`/`covered`/`total` are NOT counts. This is a batch query over
        # EvalResult by design (one round-trip for N workspaces — HF-1/T-198), and
        # only the percentage is persisted, so the real numerator/denominator are
        # not available here without reading every harness body. They are filled
        # to express the percentage out of 100 and must not be rendered as test or
        # requirement counts; the coverage chip previously did exactly that and
        # displayed "0 tests cover all 100 spec requirements".
        result[workspace_id] = CoverageSummary(
            tests=0,
            covered=pct_int,
            total=100,
            percent=pct_int,
        )

    logger.debug(
        "coverage_utils.batch_query",
        extra={
            "workspace_count": len(ids_to_query),
            "coverage_found": len(seen),
        },
    )
    return result


async def derive_coverage_summary(
    workspace_id: UUID,
    db: AsyncSession,
) -> CoverageSummary | None:
    """Return the coverage summary for a single workspace.

    Thin convenience wrapper around :func:`derive_coverage_summaries` so
    that single-workspace endpoints (``GET /workspaces/{id}``,
    ``GET /public/{slug}``, and PDF export) share the same code path and
    never drift from the batch implementation.

    HF-1 — T-198.  MF-2 — T-206.
    """
    summaries = await derive_coverage_summaries([workspace_id], db)
    return summaries.get(workspace_id)

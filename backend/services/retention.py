"""Data retention & purging jobs (issue #43).

Bounds steady-state DB size to the *active* corpus rather than lifetime history.
Mirrors the ``maintenance.py`` / ``billing_worker.purge_billing_events``
conventions: bounded-batch deletes keyed on indexed predicates, one structlog
audit row per run, and Prometheus telemetry (candidates gauge, purged counter,
run-duration histogram, last-success gauge).

Two keys must turn before *anything* deletes (plan §3.1): the master
``retention_enabled`` AND ``retention_dry_run=False``. Each tier is then gated by
its own ``retention_tierN_purge_enabled`` flag, so a job with its flag off (or in
dry-run) still *counts* candidates — feeding the gauge and the backlog alert —
but deletes nothing. Every window is a config knob so dev/staging can run 1-day
windows and see candidates actually materialise.

Jobs are idempotent and safe to re-run: each deletes at most
``retention_max_rows_per_run`` rows per run (a backlog drains over several daily
runs), commits per batch, and never touches a guarded row (current stage
versions, push-referenced versions, non-``failed`` pushes, non-terminal batch
jobs, publicly-shared/newest storyboards, active workspaces).

Dialect-neutral SQLAlchemy only — the same code runs against the sqlite unit
backend and Postgres. The purge predicates read cleanly on both; the keep-N
window functions and the whole-workspace cascade are validated against Postgres
in ``tests/test_retention.py``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import Delete, Select, bindparam, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import (
    EvalResult,
    IntegrationPush,
    LLMBatchJob,
    LLMCostEvent,
    Stage,
    StageVersion,
    Storyboard,
    Workspace,
)
from services.observability import (
    RETENTION_CANDIDATES,
    RETENTION_LAST_SUCCESS_TIMESTAMP,
    RETENTION_PURGED_ROWS,
    RETENTION_RUN_SECONDS,
    record_table_stats,
)

logger = structlog.get_logger(__name__)

# The published retention-policy version. Returned by GET /retention/policy and
# stamped by the delete dialog as ``workspaces.retention_ack_version`` (proof the
# user saw the trash notice). Bump this string when the policy page / windows
# change materially so acknowledgments are versioned (plan §5.1/§5.3).
RETENTION_POLICY_VERSION = "trash-v1"

# The FIXED table allowlist the Phase-0 size sampler tracks (plan §6 / the §2
# retention matrix). Kept small and fixed so the ``table`` gauge label is bounded
# and can never explode Prometheus cardinality. Ordered tier 0 → 4 for legibility.
TRACKED_TABLES: tuple[str, ...] = (
    # Tier 0 — provider idempotency / terminal checkout (existing TTL purges).
    "github_webhook_events",
    "stripe_webhook_events",
    "billing_webhook_events",
    "billing_checkout_attempts",
    # Tier 1 — telemetry TTL + failed-row purges.
    "llm_cost_events",
    "eval_results",
    "llm_batch_jobs",
    "integration_pushes",
    "integration_push_tasks",
    # Tier 2 — content keep-N (the byte win).
    "stage_versions",
    "storyboards",
    # Tier 3 — workspace trash + its cascade subtree.
    "workspaces",
    "stages",
    "increments",
    "increment_ideas",
    # Tier 4 — retained forever (tracked for context; never purged).
    "credit_ledger",
)

# A candidate-id selector: given an optional row limit, return a SELECT of the ids
# eligible for purge. ``None`` ⇒ no limit (used for the exact candidate count).
CandidateIdsFactory = Callable[[int | None], Select]


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _will_delete(tier_enabled: bool) -> bool:
    """Whether a job may actually delete this run (plan §3.1 two-key rule).

    Deletes only when the master switch is on, dry-run is off, AND the tier's own
    purge flag is on. With any one of them off the job still counts candidates.
    """
    return bool(
        settings.retention_enabled and not settings.retention_dry_run and tier_enabled
    )


@dataclass
class RetentionRunResult:
    """The outcome of one retention job run (returned + logged + gauged)."""

    job: str
    table: str
    candidates: int
    deleted: int
    will_delete: bool
    dry_run: bool
    purge_enabled: bool
    batch_size: int
    cap: int
    duration_seconds: float
    cutoffs: dict[str, str] = field(default_factory=dict)


async def _count(db: AsyncSession, candidate_ids: CandidateIdsFactory) -> int:
    """Exact count of purge candidates (feeds the gauge + backlog alert)."""
    stmt = select(func.count()).select_from(candidate_ids(None).subquery())
    return int((await db.execute(stmt)).scalar() or 0)


async def _batched_delete(
    db: AsyncSession,
    candidate_ids: CandidateIdsFactory,
    delete_by_ids: Callable[[list], Delete],
    *,
    batch_size: int,
    cap: int,
) -> int:
    """Delete candidates in bounded batches, committing per batch.

    Each iteration's LIMIT is clamped to the remaining per-run budget so the cap
    is honoured exactly (``cap`` candidates ⇒ exactly ``cap`` deleted, no
    over-delete). Stops when the candidate set drains or the cap is reached.
    """
    deleted = 0
    while True:
        remaining = cap - deleted
        if remaining <= 0:
            break
        limit = min(batch_size, remaining)
        ids = list((await db.execute(candidate_ids(limit))).scalars().all())
        if not ids:
            break
        await db.execute(delete_by_ids(ids))
        await db.commit()
        deleted += len(ids)
        if len(ids) < limit:
            break
    return deleted


async def _run_purge(
    db: AsyncSession,
    *,
    job: str,
    table: str,
    candidate_ids: CandidateIdsFactory,
    delete_by_ids: Callable[[list], Delete],
    tier_enabled: bool,
    cutoffs: dict[str, str],
) -> RetentionRunResult:
    """Count → gate → batched-delete → emit metrics + one audit row (plan §3.2).

    ``candidates`` is always computed and gauged (even in counting-only mode) so
    the backlog alert stays live. ``last_success`` is set only after the run
    completes cleanly — a raised exception in the caller leaves it stale so the
    missed-run pager fires.
    """
    batch_size = settings.retention_purge_batch_size
    cap = settings.retention_max_rows_per_run
    will = _will_delete(tier_enabled)

    started = time.perf_counter()
    candidates = await _count(db, candidate_ids)
    RETENTION_CANDIDATES.labels(job=job).set(candidates)

    deleted = 0
    if will:
        deleted = await _batched_delete(
            db, candidate_ids, delete_by_ids, batch_size=batch_size, cap=cap
        )
        if deleted:
            RETENTION_PURGED_ROWS.labels(job=job, table=table).inc(deleted)

    duration = time.perf_counter() - started
    RETENTION_RUN_SECONDS.labels(job=job).observe(duration)
    RETENTION_LAST_SUCCESS_TIMESTAMP.labels(job=job).set(time.time())

    result = RetentionRunResult(
        job=job,
        table=table,
        candidates=candidates,
        deleted=deleted,
        will_delete=will,
        dry_run=settings.retention_dry_run,
        purge_enabled=tier_enabled,
        batch_size=batch_size,
        cap=cap,
        duration_seconds=round(duration, 3),
        cutoffs=cutoffs,
    )
    logger.info(
        f"retention.{job}_done",
        job=job,
        table=table,
        candidates=candidates,
        deleted=deleted,
        will_delete=will,
        dry_run=result.dry_run,
        purge_enabled=tier_enabled,
        batch_size=batch_size,
        cap=cap,
        duration_seconds=result.duration_seconds,
        **{f"cutoff_{k}": v for k, v in cutoffs.items()},
    )
    return result


# ---------------------------------------------------------------------------
# Tier 1 — telemetry TTL + failed-row purges (plan §3.2)
# ---------------------------------------------------------------------------


async def purge_cost_events(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionRunResult:
    """Delete ``llm_cost_events`` older than the TTL window (index exists)."""
    cutoff = _now(now) - timedelta(days=settings.retention_cost_events_days)

    def candidate_ids(limit: int | None) -> Select:
        stmt = select(LLMCostEvent.id).where(LLMCostEvent.created_at < cutoff)
        return stmt.limit(limit) if limit is not None else stmt

    return await _run_purge(
        db,
        job="cost_events",
        table="llm_cost_events",
        candidate_ids=candidate_ids,
        delete_by_ids=lambda ids: delete(LLMCostEvent).where(LLMCostEvent.id.in_(ids)),
        tier_enabled=settings.retention_tier1_purge_enabled,
        cutoffs={"created_at": cutoff.isoformat()},
    )


async def purge_eval_results(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionRunResult:
    """Delete ``eval_results`` older than the TTL window (index from 0032).

    Tier 2 also cascade-deletes evals with their pruned stage versions; this TTL
    purge additionally reaps evals whose version is still kept but is old.
    """
    cutoff = _now(now) - timedelta(days=settings.retention_eval_results_days)

    def candidate_ids(limit: int | None) -> Select:
        stmt = select(EvalResult.id).where(EvalResult.created_at < cutoff)
        return stmt.limit(limit) if limit is not None else stmt

    return await _run_purge(
        db,
        job="eval_results",
        table="eval_results",
        candidate_ids=candidate_ids,
        delete_by_ids=lambda ids: delete(EvalResult).where(EvalResult.id.in_(ids)),
        tier_enabled=settings.retention_tier1_purge_enabled,
        cutoffs={"created_at": cutoff.isoformat()},
    )


async def purge_failed_batch_jobs(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionRunResult:
    """Delete ``failed`` ``llm_batch_jobs`` older than the window.

    Only ``failed`` rows accumulate — the lifecycle deletes a row on successful
    collect (plan §1.3). Non-terminal (``pending``/``submitted``) rows are never
    touched, and ``status`` is indexed.
    """
    cutoff = _now(now) - timedelta(days=settings.retention_failed_batch_jobs_days)

    def candidate_ids(limit: int | None) -> Select:
        stmt = select(LLMBatchJob.id).where(
            LLMBatchJob.status == "failed", LLMBatchJob.updated_at < cutoff
        )
        return stmt.limit(limit) if limit is not None else stmt

    return await _run_purge(
        db,
        job="failed_batch_jobs",
        table="llm_batch_jobs",
        candidate_ids=candidate_ids,
        delete_by_ids=lambda ids: delete(LLMBatchJob).where(LLMBatchJob.id.in_(ids)),
        tier_enabled=settings.retention_tier1_purge_enabled,
        cutoffs={"updated_at": cutoff.isoformat()},
    )


async def purge_failed_pushes(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionRunResult:
    """Delete ``failed`` ``integration_pushes`` older than the window.

    Only ``failed`` rows are garbage: the partial unique index enforces one live
    push per (workspace, repo) and re-export *reuses* it, so ``pending`` /
    ``completed`` / ``stale`` are all live sync state (plan §1.2). Push tasks die
    via the DB-level ``ON DELETE CASCADE`` on ``integration_push_tasks``.
    """
    cutoff = _now(now) - timedelta(days=settings.retention_failed_pushes_days)

    def candidate_ids(limit: int | None) -> Select:
        stmt = select(IntegrationPush.id).where(
            IntegrationPush.status == "failed", IntegrationPush.created_at < cutoff
        )
        return stmt.limit(limit) if limit is not None else stmt

    return await _run_purge(
        db,
        job="failed_pushes",
        table="integration_pushes",
        candidate_ids=candidate_ids,
        delete_by_ids=lambda ids: delete(IntegrationPush).where(
            IntegrationPush.id.in_(ids)
        ),
        tier_enabled=settings.retention_tier1_purge_enabled,
        cutoffs={"created_at": cutoff.isoformat()},
    )


async def run_tier1(db: AsyncSession) -> list[RetentionRunResult]:
    """Run all four Tier-1 jobs sequentially in one session (worker cron entry)."""
    return [
        await purge_cost_events(db),
        await purge_eval_results(db),
        await purge_failed_batch_jobs(db),
        await purge_failed_pushes(db),
    ]


# ---------------------------------------------------------------------------
# Tier 2 — content keep-N (the byte win) + storyboards (plan §4)
# ---------------------------------------------------------------------------


async def purge_stage_versions(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionRunResult:
    """Keep the last N stage versions per stage; prune the rest when > min age.

    Caps steady-state bytes at ``stages × N × avg_artifact_size`` regardless of
    account age — ``stage_versions.content`` is the dominant byte cost. Never
    deletes the current version (``version == stage.current_version``, a belt on
    top of ``rn > keep``) or a push-referenced version (the ``integration_pushes``
    → ``stage_versions`` NO-ACTION FK, guarded by ``NOT EXISTS``). ``eval_results``
    cascade automatically with each pruned version (DB-level ``ON DELETE
    CASCADE``). Uses ``ix_stage_versions_stage_id`` for the window partition.
    """
    keep = settings.retention_stage_versions_keep
    cutoff = _now(now) - timedelta(days=settings.retention_stage_versions_min_age_days)

    def candidate_ids(limit: int | None) -> Select:
        rn = (
            func.row_number()
            .over(
                partition_by=StageVersion.stage_id,
                order_by=StageVersion.version.desc(),
            )
            .label("rn")
        )
        ranked = select(
            StageVersion.id.label("id"),
            StageVersion.stage_id.label("stage_id"),
            StageVersion.version.label("version"),
            StageVersion.created_at.label("created_at"),
            rn,
        ).subquery()
        push_ref = (
            select(IntegrationPush.id)
            .where(IntegrationPush.source_stage_version_id == ranked.c.id)
            .exists()
        )
        stmt = (
            select(ranked.c.id)
            .select_from(ranked)
            .join(Stage, Stage.id == ranked.c.stage_id)
            .where(
                ranked.c.rn > keep,
                ranked.c.created_at < cutoff,
                ranked.c.version != Stage.current_version,
                ~push_ref,
            )
        )
        return stmt.limit(limit) if limit is not None else stmt

    return await _run_purge(
        db,
        job="stage_versions",
        table="stage_versions",
        candidate_ids=candidate_ids,
        delete_by_ids=lambda ids: delete(StageVersion).where(StageVersion.id.in_(ids)),
        tier_enabled=settings.retention_tier2_purge_enabled,
        cutoffs={"created_at": cutoff.isoformat(), "keep_n": str(keep)},
    )


async def purge_storyboards(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionRunResult:
    """Keep the last N storyboards per workspace; prune the rest when > min age.

    Never deletes the newest row (``rn == 1`` is always within ``keep``), a
    publicly-shared storyboard (``public_share_enabled`` — a live public link must
    not 404), or a non-terminal one (``status == 'generating'``).
    ``llm_cost_events.storyboard_id`` is ``SET NULL`` so cost history survives.
    """
    keep = settings.retention_storyboards_keep
    cutoff = _now(now) - timedelta(days=settings.retention_storyboards_min_age_days)

    def candidate_ids(limit: int | None) -> Select:
        rn = (
            func.row_number()
            .over(
                partition_by=Storyboard.workspace_id,
                order_by=Storyboard.version.desc(),
            )
            .label("rn")
        )
        ranked = select(
            Storyboard.id.label("id"),
            Storyboard.created_at.label("created_at"),
            Storyboard.public_share_enabled.label("public_share_enabled"),
            Storyboard.status.label("status"),
            rn,
        ).subquery()
        stmt = select(ranked.c.id).where(
            ranked.c.rn > keep,
            ranked.c.created_at < cutoff,
            ranked.c.public_share_enabled.is_(False),
            ranked.c.status != "generating",
        )
        return stmt.limit(limit) if limit is not None else stmt

    return await _run_purge(
        db,
        job="storyboards",
        table="storyboards",
        candidate_ids=candidate_ids,
        delete_by_ids=lambda ids: delete(Storyboard).where(Storyboard.id.in_(ids)),
        tier_enabled=settings.retention_tier2_purge_enabled,
        cutoffs={"created_at": cutoff.isoformat(), "keep_n": str(keep)},
    )


async def run_tier2(db: AsyncSession) -> list[RetentionRunResult]:
    """Run both Tier-2 keep-N jobs sequentially in one session (worker cron)."""
    return [
        await purge_stage_versions(db),
        await purge_storyboards(db),
    ]


# ---------------------------------------------------------------------------
# Tier 3 — workspace trash lifecycle (user-facing; plan §5.2)
# ---------------------------------------------------------------------------

# The structlog audit event emitted per hard-deleted workspace (plan §5.2). One
# row per workspace, id-shaped fields only — never problem-statement/content.
AUDIT_EVENT_WORKSPACE_PURGED = "retention.workspace_purged"


def _trashed_workspace_predicate(now: datetime):
    """The Tier-3 deletability predicate (plan §5.2).

    A workspace is deletable iff ``status='archived'`` AND either:
      - post-deploy delete (``retention_ack_version IS NOT NULL``): archived more
        than ``retention_trash_days`` ago; or
      - legacy / un-acked row (``retention_ack_version IS NULL``): archived more
        than the conservative ``retention_legacy_archived_days`` ago.
    ``archived_at IS NOT NULL`` is required so a mis-migrated row is never
    eligible on a NULL clock.
    """
    acked_cutoff = now - timedelta(days=settings.retention_trash_days)
    legacy_cutoff = now - timedelta(days=settings.retention_legacy_archived_days)
    return (
        (Workspace.status == "archived")
        & Workspace.archived_at.is_not(None)
        & (
            (
                Workspace.retention_ack_version.is_not(None)
                & (Workspace.archived_at < acked_cutoff)
            )
            | (
                Workspace.retention_ack_version.is_(None)
                & (Workspace.archived_at < legacy_cutoff)
            )
        )
    )


async def purge_trashed_workspaces(
    db: AsyncSession, *, now: datetime | None = None
) -> RetentionRunResult:
    """Hard-delete expired trashed workspaces + their full subtree (plan §5.2).

    Bespoke (not the generic id-batch helper) because §5.2 requires a per-row
    audit row *before* the delete. One ``DELETE FROM workspaces WHERE id IN
    (batch)`` fans the cascade out to stages → versions → evals, increments,
    ideas, storyboards, pushes → push tasks in-statement (safe w.r.t. the
    push→version NO-ACTION FK — both die in the same statement). ``llm_cost_events``
    survive via ``SET NULL``; ``credit_ledger`` is untouched (its only FK is
    ``user_id``). Never deletes an active workspace or one whose clock has not
    expired — enforced by the predicate itself.
    """
    now = _now(now)
    predicate = _trashed_workspace_predicate(now)
    tier_enabled = settings.retention_tier3_purge_enabled
    batch_size = settings.retention_purge_batch_size
    cap = settings.retention_max_rows_per_run
    will = _will_delete(tier_enabled)

    started = time.perf_counter()
    candidates = int(
        (
            await db.execute(
                select(func.count()).select_from(
                    select(Workspace.id).where(predicate).subquery()
                )
            )
        ).scalar()
        or 0
    )
    RETENTION_CANDIDATES.labels(job="trashed_workspaces").set(candidates)

    deleted = 0
    if will:
        while True:
            remaining = cap - deleted
            if remaining <= 0:
                break
            limit = min(batch_size, remaining)
            rows = list(
                (
                    await db.execute(
                        select(
                            Workspace.id,
                            Workspace.user_id,
                            Workspace.archived_at,
                            Workspace.retention_ack_version,
                        )
                        .where(predicate)
                        .limit(limit)
                    )
                ).all()
            )
            if not rows:
                break
            for row in rows:
                # Per-row audit BEFORE the delete (plan §5.2). Id-shaped only.
                logger.info(
                    AUDIT_EVENT_WORKSPACE_PURGED,
                    workspace_id=str(row.id),
                    user_id=str(row.user_id),
                    archived_at=(
                        row.archived_at.isoformat() if row.archived_at else None
                    ),
                    ack_version=row.retention_ack_version,
                )
            ids = [row.id for row in rows]
            await db.execute(delete(Workspace).where(Workspace.id.in_(ids)))
            await db.commit()
            deleted += len(ids)
            if len(ids) < limit:
                break
        if deleted:
            RETENTION_PURGED_ROWS.labels(
                job="trashed_workspaces", table="workspaces"
            ).inc(deleted)

    duration = time.perf_counter() - started
    RETENTION_RUN_SECONDS.labels(job="trashed_workspaces").observe(duration)
    RETENTION_LAST_SUCCESS_TIMESTAMP.labels(job="trashed_workspaces").set(time.time())

    cutoffs = {
        "acked_before": (
            now - timedelta(days=settings.retention_trash_days)
        ).isoformat(),
        "legacy_before": (
            now - timedelta(days=settings.retention_legacy_archived_days)
        ).isoformat(),
    }
    result = RetentionRunResult(
        job="trashed_workspaces",
        table="workspaces",
        candidates=candidates,
        deleted=deleted,
        will_delete=will,
        dry_run=settings.retention_dry_run,
        purge_enabled=tier_enabled,
        batch_size=batch_size,
        cap=cap,
        duration_seconds=round(duration, 3),
        cutoffs=cutoffs,
    )
    logger.info(
        "retention.trashed_workspaces_done",
        job="trashed_workspaces",
        table="workspaces",
        candidates=candidates,
        deleted=deleted,
        will_delete=will,
        dry_run=result.dry_run,
        purge_enabled=tier_enabled,
        batch_size=batch_size,
        cap=cap,
        duration_seconds=result.duration_seconds,
        cutoff_acked_before=cutoffs["acked_before"],
        cutoff_legacy_before=cutoffs["legacy_before"],
    )
    return result


# ---------------------------------------------------------------------------
# Phase 0 — table-size sampler (plan §6). Ships FIRST, zero risk: read-only.
# ---------------------------------------------------------------------------

# One query returns size + live-tuple estimate for every tracked table that
# exists. ``pg_stat_user_tables`` lists a table once created (n_live_tup may be 0
# until analyzed), and ``pg_total_relation_size(relid)`` includes indexes + TOAST.
_TABLE_STATS_SQL = text(
    "SELECT relname, pg_total_relation_size(relid) AS bytes, n_live_tup "
    "FROM pg_stat_user_tables WHERE relname IN :tables"
).bindparams(bindparam("tables", expanding=True))


async def sample_table_stats(
    db: AsyncSession,
) -> dict[str, tuple[int | None, int | None]]:
    """Sample on-disk size + live-tuple count for the tracked tables (plan §6).

    Postgres-only (``pg_stat_user_tables`` / ``pg_total_relation_size``); a
    non-postgres backend returns ``{}`` cleanly. Publishes the
    ``thought2build_db_table_bytes`` / ``thought2build_db_table_live_tuples``
    gauges — the size baseline every later "size stabilized" claim is judged
    against, and the evidence for tuning the §2 windows before anything
    deletes. Read-only; no
    commit. Returns the sampled ``{table: (bytes, live_tuples)}`` for tests.
    """
    bind = db.bind
    if bind is None or bind.dialect.name != "postgresql":
        return {}

    rows = (await db.execute(_TABLE_STATS_SQL, {"tables": list(TRACKED_TABLES)})).all()
    sampled: dict[str, tuple[int | None, int | None]] = {}
    for row in rows:
        size_bytes = int(row.bytes) if row.bytes is not None else None
        live_tuples = int(row.n_live_tup) if row.n_live_tup is not None else None
        sampled[row.relname] = (size_bytes, live_tuples)
        record_table_stats(row.relname, size_bytes, live_tuples)
    logger.info("retention.table_stats_done", tables=len(sampled))
    return sampled

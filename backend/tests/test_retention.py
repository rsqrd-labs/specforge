"""Data retention & purging tests (issue #43).

Exercised against the live PostgreSQL instance (same pattern as
``test_maintenance.py`` / ``test_credit_cycle_integration.py``) because the purge
predicates use window functions and rely on the real FK cascade semantics that a
sqlite/FakeDB double cannot reproduce.

Purges are GLOBAL (a ``dry_run=False`` job deletes every eligible row in the DB,
not just this test's), so — mirroring ``test_maintenance`` — every test tags its
rows and asserts on its *own* ids: seeded old ids gone, seeded recent/guarded ids
survive. The batch-cap test is the one exception and clears its (rare) candidate
set first so the count is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import config
from config import settings
from models import (
    CreditLedger,
    EvalResult,
    IntegrationPush,
    LLMBatchJob,
    LLMCostEvent,
    Stage,
    StageVersion,
    Storyboard,
    User,
    Workspace,
)
from services import retention

_PROBLEM_STATEMENT = (
    "I want to build a task management web app for teams to create projects, "
    "assign tasks, track status, and notify users about important changes."
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Test environment: a sessionmaker + a cleanup registry (users cascade-clean
# their whole subtree; non-user rows are registered explicitly).
# ---------------------------------------------------------------------------


@dataclass
class _Env:
    maker: async_sessionmaker
    users: list[UUID] = field(default_factory=list)
    extra: list[tuple] = field(default_factory=list)  # (model, column, value)


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    e = _Env(maker=maker)
    try:
        yield e
    finally:
        async with maker() as db:
            for model, col, val in e.extra:
                await db.execute(delete(model).where(col == val))
            if e.users:
                await db.execute(delete(User).where(User.id.in_(e.users)))
            await db.commit()
        await engine.dispose()


@pytest.fixture(autouse=True)
def _enable_purges(monkeypatch):
    """Default every test to the "will actually delete" gate (master on, dry-run
    off, both tier flags on). Individual tests override to exercise the gates."""
    monkeypatch.setattr(settings, "retention_enabled", True, raising=False)
    monkeypatch.setattr(settings, "retention_dry_run", False, raising=False)
    monkeypatch.setattr(settings, "retention_tier1_purge_enabled", True, raising=False)
    monkeypatch.setattr(settings, "retention_tier2_purge_enabled", True, raising=False)
    monkeypatch.setattr(settings, "retention_tier3_purge_enabled", True, raising=False)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db, env: _Env) -> User:
    user = User(
        email=f"ret-{uuid4()}@example.com",
        google_id=f"g-{uuid4()}",
        name="Retention User",
        credit_balance=0,
        created_at=_now(),
    )
    db.add(user)
    await db.flush()
    env.users.append(user.id)
    return user


def _workspace(user: User, *, status: str = "active", **kw) -> Workspace:
    return Workspace(
        user_id=user.id,
        name="Retention WS",
        problem_statement=_PROBLEM_STATEMENT,
        provider="anthropic",
        model="claude-haiku-4-5",
        status=status,
        **kw,
    )


def _stage(workspace: Workspace, *, current_version: int = 0, **kw) -> Stage:
    return Stage(
        workspace_id=workspace.id,
        type="spec",
        status="finalised",
        content="body",
        current_version=current_version,
        review_gate_acknowledged=True,
        **kw,
    )


def _version(stage: Stage, version: int, created_at: datetime, **kw) -> StageVersion:
    return StageVersion(
        stage_id=stage.id,
        version=version,
        content=f"content v{version}",
        created_by="ai",
        created_at=created_at,
        **kw,
    )


def _eval(version: StageVersion, created_at: datetime) -> EvalResult:
    return EvalResult(
        stage_version_id=version.id,
        stage_type="spec",
        overall_score=80,
        created_at=created_at,
    )


def _storyboard(
    workspace: Workspace,
    user: User,
    version: int,
    created_at: datetime,
    *,
    status: str = "ready",
    public_share_enabled: bool = False,
) -> Storyboard:
    return Storyboard(
        workspace_id=workspace.id,
        user_id=user.id,
        version=version,
        status=status,
        title="Keynote",
        theme="indica",
        content_json={},
        speaker_notes_md="",
        demo_script_md="",
        technical_appendix_md="",
        source_map_json={},
        source_stage_version_ids={},
        public_share_enabled=public_share_enabled,
        created_at=created_at,
    )


def _push(
    workspace: Workspace,
    user: User,
    *,
    status: str,
    created_at: datetime,
    repo_id: int | None = None,
    source_stage_version_id: UUID | None = None,
) -> IntegrationPush:
    return IntegrationPush(
        workspace_id=workspace.id,
        user_id=user.id,
        provider="github",
        repo_id=repo_id,
        repo_full_name="owner/repo",
        status=status,
        created_at=created_at,
        source_stage_version_id=source_stage_version_id,
    )


# ---------------------------------------------------------------------------
# Tier 1 — telemetry TTL + failed-row purges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_events_old_deleted_recent_kept(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_cost_events_days", 30, raising=False)
    tag = uuid4().hex
    old_gen, recent_gen = f"old-{tag}", f"recent-{tag}"
    env.extra.append((LLMCostEvent, LLMCostEvent.generation_id, recent_gen))

    async with env.maker() as db:
        db.add(
            LLMCostEvent(
                generation_id=old_gen,
                provider="anthropic",
                model="haiku",
                created_at=_now() - timedelta(days=40),
            )
        )
        db.add(
            LLMCostEvent(
                generation_id=recent_gen,
                provider="anthropic",
                model="haiku",
                created_at=_now() - timedelta(days=1),
            )
        )
        await db.commit()

    async with env.maker() as db:
        result = await retention.purge_cost_events(db)

    assert result.deleted >= 1
    async with env.maker() as db:
        remaining = set(
            (
                await db.execute(
                    select(LLMCostEvent.generation_id).where(
                        LLMCostEvent.generation_id.in_([old_gen, recent_gen])
                    )
                )
            )
            .scalars()
            .all()
        )
    assert old_gen not in remaining
    assert recent_gen in remaining


@pytest.mark.asyncio
async def test_dry_run_counts_but_deletes_nothing(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_dry_run", True, raising=False)
    monkeypatch.setattr(settings, "retention_cost_events_days", 30, raising=False)
    tag = uuid4().hex
    gen = f"dry-{tag}"
    env.extra.append((LLMCostEvent, LLMCostEvent.generation_id, gen))

    async with env.maker() as db:
        db.add(
            LLMCostEvent(
                generation_id=gen,
                provider="anthropic",
                model="haiku",
                created_at=_now() - timedelta(days=40),
            )
        )
        await db.commit()

    async with env.maker() as db:
        result = await retention.purge_cost_events(db)

    assert result.candidates >= 1
    assert result.deleted == 0
    assert result.will_delete is False
    async with env.maker() as db:
        still_there = (
            await db.execute(
                select(LLMCostEvent.id).where(LLMCostEvent.generation_id == gen)
            )
        ).scalar_one_or_none()
    assert still_there is not None


@pytest.mark.asyncio
async def test_tier_flag_off_counts_only_even_when_not_dry_run(env, monkeypatch):
    # dry_run=False but the Tier-1 flag is off ⇒ counting only, nothing deleted.
    monkeypatch.setattr(settings, "retention_dry_run", False, raising=False)
    monkeypatch.setattr(settings, "retention_tier1_purge_enabled", False, raising=False)
    monkeypatch.setattr(settings, "retention_cost_events_days", 30, raising=False)
    tag = uuid4().hex
    gen = f"flagoff-{tag}"
    env.extra.append((LLMCostEvent, LLMCostEvent.generation_id, gen))

    async with env.maker() as db:
        db.add(
            LLMCostEvent(
                generation_id=gen,
                provider="anthropic",
                model="haiku",
                created_at=_now() - timedelta(days=40),
            )
        )
        await db.commit()

    async with env.maker() as db:
        result = await retention.purge_cost_events(db)

    assert result.candidates >= 1
    assert result.deleted == 0
    async with env.maker() as db:
        still_there = (
            await db.execute(
                select(LLMCostEvent.id).where(LLMCostEvent.generation_id == gen)
            )
        ).scalar_one_or_none()
    assert still_there is not None


@pytest.mark.asyncio
async def test_batch_cap_honored(env, monkeypatch):
    # Insert cap+1 candidates → exactly cap deleted, one left. The candidate set is
    # cleared first so the global-purge count is deterministic (failed batch jobs
    # are rare); rows are tagged by `operation` for cleanup.
    monkeypatch.setattr(settings, "retention_max_rows_per_run", 5, raising=False)
    monkeypatch.setattr(settings, "retention_purge_batch_size", 1000, raising=False)
    monkeypatch.setattr(settings, "retention_failed_batch_jobs_days", 30, raising=False)
    tag = f"cap-{uuid4().hex}"
    env.extra.append((LLMBatchJob, LLMBatchJob.operation, tag))
    old = _now() - timedelta(days=40)

    async with env.maker() as db:
        # Clean the candidate set so only our rows match the predicate.
        await db.execute(delete(LLMBatchJob).where(LLMBatchJob.status == "failed"))
        for i in range(6):
            db.add(
                LLMBatchJob(
                    status="failed",
                    operation=tag,
                    provider="anthropic",
                    model="haiku",
                    custom_id=f"{tag}-{i}",
                    request_system="s",
                    request_user="u",
                    max_tokens=100,
                    context={},
                    created_at=old,
                    updated_at=old,
                )
            )
        await db.commit()

    async with env.maker() as db:
        result = await retention.purge_failed_batch_jobs(db)

    assert result.candidates == 6
    assert result.deleted == 5
    async with env.maker() as db:
        remaining = (
            await db.execute(
                select(func.count()).select_from(
                    select(LLMBatchJob.id)
                    .where(LLMBatchJob.operation == tag)
                    .subquery()
                )
            )
        ).scalar()
    assert remaining == 1


@pytest.mark.asyncio
async def test_failed_batch_jobs_only_terminal_purged(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_failed_batch_jobs_days", 30, raising=False)
    tag = f"terminal-{uuid4().hex}"
    env.extra.append((LLMBatchJob, LLMBatchJob.operation, tag))
    old = _now() - timedelta(days=40)

    async with env.maker() as db:
        for st in ("failed", "pending", "submitted"):
            db.add(
                LLMBatchJob(
                    status=st,
                    operation=tag,
                    provider="anthropic",
                    model="haiku",
                    custom_id=f"{tag}-{st}",
                    request_system="s",
                    request_user="u",
                    max_tokens=100,
                    context={},
                    created_at=old,
                    updated_at=old,
                )
            )
        await db.commit()

    async with env.maker() as db:
        await retention.purge_failed_batch_jobs(db)

    async with env.maker() as db:
        statuses = set(
            (
                await db.execute(
                    select(LLMBatchJob.status).where(LLMBatchJob.operation == tag)
                )
            )
            .scalars()
            .all()
        )
    assert statuses == {"pending", "submitted"}


@pytest.mark.asyncio
async def test_failed_pushes_only_failed_purged(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_failed_pushes_days", 90, raising=False)
    old = _now() - timedelta(days=120)

    async with env.maker() as db:
        user = await _seed_user(db, env)
        ws = _workspace(user)
        db.add(ws)
        await db.flush()
        # One live push per (workspace, repo) for non-failed statuses ⇒ distinct
        # repo_ids so the partial unique index is not violated.
        pushes = {
            "failed": _push(ws, user, status="failed", created_at=old, repo_id=1),
            "completed": _push(ws, user, status="completed", created_at=old, repo_id=2),
            "stale": _push(ws, user, status="stale", created_at=old, repo_id=3),
            "pending": _push(ws, user, status="pending", created_at=old, repo_id=4),
        }
        for p in pushes.values():
            db.add(p)
        await db.commit()
        ids = {k: v.id for k, v in pushes.items()}

    async with env.maker() as db:
        await retention.purge_failed_pushes(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(IntegrationPush.id).where(
                        IntegrationPush.id.in_(list(ids.values()))
                    )
                )
            )
            .scalars()
            .all()
        )
    assert ids["failed"] not in surviving
    assert ids["completed"] in surviving
    assert ids["stale"] in surviving
    assert ids["pending"] in surviving


@pytest.mark.asyncio
async def test_eval_results_ttl_purge(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_eval_results_days", 30, raising=False)

    async with env.maker() as db:
        user = await _seed_user(db, env)
        ws = _workspace(user)
        db.add(ws)
        await db.flush()
        stage = _stage(ws, current_version=1)
        db.add(stage)
        await db.flush()
        v = _version(stage, 1, _now() - timedelta(days=200))
        db.add(v)
        await db.flush()
        old_eval = _eval(v, _now() - timedelta(days=40))
        recent_eval = _eval(v, _now() - timedelta(days=1))
        db.add(old_eval)
        db.add(recent_eval)
        await db.commit()
        old_id, recent_id = old_eval.id, recent_eval.id

    async with env.maker() as db:
        await retention.purge_eval_results(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(EvalResult.id).where(EvalResult.id.in_([old_id, recent_id]))
                )
            )
            .scalars()
            .all()
        )
    assert old_id not in surviving
    assert recent_id in surviving


# ---------------------------------------------------------------------------
# Tier 2 — stage_versions keep-N + storyboards
# ---------------------------------------------------------------------------


async def _seed_versions(
    db, env, *, current_version: int, created_at: datetime, count: int = 5
):
    user = await _seed_user(db, env)
    ws = _workspace(user)
    db.add(ws)
    await db.flush()
    stage = _stage(ws, current_version=current_version)
    db.add(stage)
    await db.flush()
    versions = {}
    for n in range(1, count + 1):
        v = _version(stage, n, created_at)
        db.add(v)
        versions[n] = v
    await db.flush()
    return user, ws, stage, versions


@pytest.mark.asyncio
async def test_stage_versions_keep_n_prunes_oldest(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_stage_versions_keep", 2, raising=False)
    monkeypatch.setattr(
        settings, "retention_stage_versions_min_age_days", 1, raising=False
    )
    old = _now() - timedelta(days=30)

    async with env.maker() as db:
        _, _, _, versions = await _seed_versions(
            db, env, current_version=5, created_at=old
        )
        # Attach an eval to v1 (a pruned candidate) to prove the cascade.
        ev = _eval(versions[1], old)
        db.add(ev)
        await db.commit()
        ids = {n: v.id for n, v in versions.items()}
        eval_id = ev.id

    async with env.maker() as db:
        await retention.purge_stage_versions(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(StageVersion.id).where(
                        StageVersion.id.in_(list(ids.values()))
                    )
                )
            )
            .scalars()
            .all()
        )
        eval_gone = (
            await db.execute(select(EvalResult.id).where(EvalResult.id == eval_id))
        ).scalar_one_or_none()
    # keep=2 ⇒ versions 4 & 5 (rn 1,2) survive; 1,2,3 pruned.
    assert ids[5] in surviving
    assert ids[4] in surviving
    assert ids[3] not in surviving
    assert ids[2] not in surviving
    assert ids[1] not in surviving
    assert eval_gone is None  # cascaded with pruned v1


@pytest.mark.asyncio
async def test_stage_versions_current_version_survives_beyond_n(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_stage_versions_keep", 2, raising=False)
    monkeypatch.setattr(
        settings, "retention_stage_versions_min_age_days", 1, raising=False
    )
    old = _now() - timedelta(days=30)

    async with env.maker() as db:
        # current_version = 1 (rn 5, well beyond keep) — the belt must save it.
        _, _, _, versions = await _seed_versions(
            db, env, current_version=1, created_at=old
        )
        await db.commit()
        ids = {n: v.id for n, v in versions.items()}

    async with env.maker() as db:
        await retention.purge_stage_versions(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(StageVersion.id).where(
                        StageVersion.id.in_(list(ids.values()))
                    )
                )
            )
            .scalars()
            .all()
        )
    assert ids[1] in surviving  # current_version, saved despite rn>keep
    assert ids[5] in surviving  # rn 1
    assert ids[4] in surviving  # rn 2
    assert ids[3] not in surviving
    assert ids[2] not in surviving


@pytest.mark.asyncio
async def test_stage_versions_push_referenced_survives(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_stage_versions_keep", 2, raising=False)
    monkeypatch.setattr(
        settings, "retention_stage_versions_min_age_days", 1, raising=False
    )
    old = _now() - timedelta(days=30)

    async with env.maker() as db:
        user, ws, _, versions = await _seed_versions(
            db, env, current_version=5, created_at=old
        )
        # A push references v2 (a prune candidate at rn 4) — NOT EXISTS must save it.
        db.add(
            _push(
                ws,
                user,
                status="completed",
                created_at=old,
                repo_id=99,
                source_stage_version_id=versions[2].id,
            )
        )
        await db.commit()
        ids = {n: v.id for n, v in versions.items()}

    async with env.maker() as db:
        await retention.purge_stage_versions(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(StageVersion.id).where(
                        StageVersion.id.in_(list(ids.values()))
                    )
                )
            )
            .scalars()
            .all()
        )
    assert ids[2] in surviving  # push-referenced, saved despite rn>keep
    assert ids[3] not in surviving
    assert ids[1] not in surviving


@pytest.mark.asyncio
async def test_stage_versions_age_floor_respected(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_stage_versions_keep", 2, raising=False)
    monkeypatch.setattr(
        settings, "retention_stage_versions_min_age_days", 90, raising=False
    )
    recent = _now() - timedelta(days=1)  # within the 90-day age floor

    async with env.maker() as db:
        _, _, _, versions = await _seed_versions(
            db, env, current_version=5, created_at=recent
        )
        await db.commit()
        ids = {n: v.id for n, v in versions.items()}

    async with env.maker() as db:
        result = await retention.purge_stage_versions(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(StageVersion.id).where(
                        StageVersion.id.in_(list(ids.values()))
                    )
                )
            )
            .scalars()
            .all()
        )
    # All 5 survive — none is older than the 90-day floor.
    assert surviving == set(ids.values())
    assert result.deleted == 0


async def _seed_storyboards(db, env, created_at, *, count=4):
    user = await _seed_user(db, env)
    ws = _workspace(user)
    db.add(ws)
    await db.flush()
    boards = {}
    for n in range(1, count + 1):
        b = _storyboard(ws, user, n, created_at)
        db.add(b)
        boards[n] = b
    await db.flush()
    return user, ws, boards


@pytest.mark.asyncio
async def test_storyboards_keep_n_prunes_oldest(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_storyboards_keep", 2, raising=False)
    monkeypatch.setattr(
        settings, "retention_storyboards_min_age_days", 1, raising=False
    )
    old = _now() - timedelta(days=30)

    async with env.maker() as db:
        _, _, boards = await _seed_storyboards(db, env, old)
        await db.commit()
        ids = {n: b.id for n, b in boards.items()}

    async with env.maker() as db:
        await retention.purge_storyboards(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(Storyboard.id).where(Storyboard.id.in_(list(ids.values())))
                )
            )
            .scalars()
            .all()
        )
    # keep=2 ⇒ v3,v4 (rn 1,2) survive; v1,v2 pruned.
    assert ids[4] in surviving
    assert ids[3] in surviving
    assert ids[2] not in surviving
    assert ids[1] not in surviving


@pytest.mark.asyncio
async def test_storyboards_shared_and_generating_survive(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_storyboards_keep", 2, raising=False)
    monkeypatch.setattr(
        settings, "retention_storyboards_min_age_days", 1, raising=False
    )
    old = _now() - timedelta(days=30)

    async with env.maker() as db:
        user = await _seed_user(db, env)
        ws = _workspace(user)
        db.add(ws)
        await db.flush()
        # v1 is publicly shared, v2 is still generating — both beyond keep=2 but
        # both guarded. v3,v4 are ordinary ready boards (rn 1,2 survive by keep).
        shared = _storyboard(ws, user, 1, old, public_share_enabled=True)
        generating = _storyboard(ws, user, 2, old, status="generating")
        b3 = _storyboard(ws, user, 3, old)
        b4 = _storyboard(ws, user, 4, old)
        for b in (shared, generating, b3, b4):
            db.add(b)
        await db.commit()
        shared_id, generating_id = shared.id, generating.id

    async with env.maker() as db:
        await retention.purge_storyboards(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(Storyboard.id).where(
                        Storyboard.id.in_([shared_id, generating_id])
                    )
                )
            )
            .scalars()
            .all()
        )
    assert shared_id in surviving
    assert generating_id in surviving


@pytest.mark.asyncio
async def test_storyboards_newest_survives_regardless_of_age(env, monkeypatch):
    # A single, very old storyboard is always rn 1 (within keep) — never pruned.
    monkeypatch.setattr(settings, "retention_storyboards_keep", 1, raising=False)
    monkeypatch.setattr(
        settings, "retention_storyboards_min_age_days", 1, raising=False
    )
    old = _now() - timedelta(days=3650)

    async with env.maker() as db:
        _, _, boards = await _seed_storyboards(db, env, old, count=1)
        await db.commit()
        only_id = boards[1].id

    async with env.maker() as db:
        await retention.purge_storyboards(db)

    async with env.maker() as db:
        still_there = (
            await db.execute(select(Storyboard.id).where(Storyboard.id == only_id))
        ).scalar_one_or_none()
    assert still_there is not None


# ---------------------------------------------------------------------------
# Tier 3 — workspace trash lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trash_acked_workspace_purged_after_window(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_trash_days", 30, raising=False)

    async with env.maker() as db:
        user = await _seed_user(db, env)
        ws = _workspace(
            user,
            status="archived",
            archived_at=_now() - timedelta(days=40),
            retention_ack_version="trash-v1",
        )
        db.add(ws)
        await db.commit()
        ws_id = ws.id

    async with env.maker() as db:
        result = await retention.purge_trashed_workspaces(db)

    assert result.deleted >= 1
    async with env.maker() as db:
        gone = (
            await db.execute(select(Workspace.id).where(Workspace.id == ws_id))
        ).scalar_one_or_none()
    assert gone is None


@pytest.mark.asyncio
async def test_trash_acked_clock_not_expired_is_no_op(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_trash_days", 30, raising=False)

    async with env.maker() as db:
        user = await _seed_user(db, env)
        ws = _workspace(
            user,
            status="archived",
            archived_at=_now() - timedelta(days=5),  # within the 30-day window
            retention_ack_version="trash-v1",
        )
        db.add(ws)
        await db.commit()
        ws_id = ws.id

    async with env.maker() as db:
        await retention.purge_trashed_workspaces(db)

    async with env.maker() as db:
        still_there = (
            await db.execute(select(Workspace.id).where(Workspace.id == ws_id))
        ).scalar_one_or_none()
    assert still_there is not None


@pytest.mark.asyncio
async def test_trash_legacy_window_is_conservative(env, monkeypatch):
    # An un-acked (legacy) row uses the 180-day window, not the 30-day one.
    monkeypatch.setattr(settings, "retention_trash_days", 30, raising=False)
    monkeypatch.setattr(settings, "retention_legacy_archived_days", 180, raising=False)

    async with env.maker() as db:
        user = await _seed_user(db, env)
        # 40 days old, no ack: past the acked window but well within the legacy one.
        within_legacy = _workspace(
            user,
            status="archived",
            archived_at=_now() - timedelta(days=40),
            retention_ack_version=None,
        )
        # 200 days old, no ack: past the legacy window ⇒ eligible.
        past_legacy = _workspace(
            user,
            status="archived",
            archived_at=_now() - timedelta(days=200),
            retention_ack_version=None,
        )
        db.add(within_legacy)
        db.add(past_legacy)
        await db.commit()
        within_id, past_id = within_legacy.id, past_legacy.id

    async with env.maker() as db:
        await retention.purge_trashed_workspaces(db)

    async with env.maker() as db:
        surviving = set(
            (
                await db.execute(
                    select(Workspace.id).where(Workspace.id.in_([within_id, past_id]))
                )
            )
            .scalars()
            .all()
        )
    assert within_id in surviving  # legacy window not yet reached
    assert past_id not in surviving  # past the conservative legacy window


@pytest.mark.asyncio
async def test_trash_active_workspace_never_purged(env, monkeypatch):
    monkeypatch.setattr(settings, "retention_trash_days", 1, raising=False)
    monkeypatch.setattr(settings, "retention_legacy_archived_days", 1, raising=False)

    async with env.maker() as db:
        user = await _seed_user(db, env)
        # Active, but with an ancient archived_at as a stress fixture — the
        # status='active' guard must keep it regardless.
        ws = _workspace(user, status="active", archived_at=_now() - timedelta(days=999))
        db.add(ws)
        await db.commit()
        ws_id = ws.id

    async with env.maker() as db:
        await retention.purge_trashed_workspaces(db)

    async with env.maker() as db:
        still_there = (
            await db.execute(select(Workspace.id).where(Workspace.id == ws_id))
        ).scalar_one_or_none()
    assert still_there is not None


@pytest.mark.asyncio
async def test_trash_cascade_leaves_ledger_and_cost_events(env, monkeypatch):
    # Deleting a trashed workspace fans the cascade across its subtree but must
    # leave financial rows (credit_ledger, user_id FK) and cost history
    # (llm_cost_events, workspace_id SET NULL) intact.
    monkeypatch.setattr(settings, "retention_trash_days", 30, raising=False)
    cost_gen = f"cascade-{uuid4().hex}"
    env.extra.append((LLMCostEvent, LLMCostEvent.generation_id, cost_gen))

    async with env.maker() as db:
        user = await _seed_user(db, env)
        ws = _workspace(
            user,
            status="archived",
            archived_at=_now() - timedelta(days=40),
            retention_ack_version="trash-v1",
        )
        db.add(ws)
        await db.flush()
        stage = _stage(ws, current_version=1)
        db.add(stage)
        await db.flush()
        v = _version(stage, 1, _now() - timedelta(days=40))
        db.add(v)
        db.add(_storyboard(ws, user, 1, _now() - timedelta(days=40)))
        db.add(_push(ws, user, status="failed", created_at=_now(), repo_id=7))
        ledger = CreditLedger(user_id=user.id, amount=-10, reason="generation")
        db.add(ledger)
        db.add(
            LLMCostEvent(
                generation_id=cost_gen,
                provider="anthropic",
                model="haiku",
                created_at=_now(),
                workspace_id=ws.id,
            )
        )
        await db.commit()
        ws_id, ledger_id, version_id = ws.id, ledger.id, v.id

    async with env.maker() as db:
        await retention.purge_trashed_workspaces(db)

    async with env.maker() as db:
        assert (
            await db.execute(select(Workspace.id).where(Workspace.id == ws_id))
        ).scalar_one_or_none() is None
        assert (
            await db.execute(
                select(StageVersion.id).where(StageVersion.id == version_id)
            )
        ).scalar_one_or_none() is None
        # Financial ledger untouched.
        assert (
            await db.execute(
                select(CreditLedger.id).where(CreditLedger.id == ledger_id)
            )
        ).scalar_one_or_none() is not None
        # Cost event survives with workspace_id nulled (SET NULL).
        cost_ws = (
            await db.execute(
                select(LLMCostEvent.workspace_id).where(
                    LLMCostEvent.generation_id == cost_gen
                )
            )
        ).scalar_one_or_none()
    assert cost_ws is None


# ---------------------------------------------------------------------------
# Gates + config + Phase 0
# ---------------------------------------------------------------------------


def test_will_delete_two_key_rule(monkeypatch):
    monkeypatch.setattr(settings, "retention_enabled", True, raising=False)
    monkeypatch.setattr(settings, "retention_dry_run", False, raising=False)
    assert retention._will_delete(True) is True
    assert retention._will_delete(False) is False  # tier flag off

    monkeypatch.setattr(settings, "retention_dry_run", True, raising=False)
    assert retention._will_delete(True) is False  # dry-run on

    monkeypatch.setattr(settings, "retention_dry_run", False, raising=False)
    monkeypatch.setattr(settings, "retention_enabled", False, raising=False)
    assert retention._will_delete(True) is False  # master off


def test_prod_validation_tier3_floors(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production", raising=False)
    monkeypatch.setattr(settings, "retention_tier3_purge_enabled", True, raising=False)
    monkeypatch.setattr(settings, "retention_trash_days", 1, raising=False)
    monkeypatch.setattr(settings, "retention_legacy_archived_days", 10, raising=False)
    with pytest.raises(RuntimeError) as exc:
        config.validate_production_settings()
    msg = str(exc.value)
    assert "RETENTION_TRASH_DAYS" in msg
    assert "RETENTION_LEGACY_ARCHIVED_DAYS" in msg


def test_prod_validation_tier3_floors_pass_when_sane(monkeypatch):
    # With the flag off, the trash floors are not enforced even at low windows.
    monkeypatch.setattr(settings, "environment", "production", raising=False)
    monkeypatch.setattr(settings, "retention_tier3_purge_enabled", False, raising=False)
    monkeypatch.setattr(settings, "retention_trash_days", 1, raising=False)
    try:
        config.validate_production_settings()
    except RuntimeError as exc:
        # Other prod-config errors may fire; only the trash floor must be absent.
        assert "RETENTION_TRASH_DAYS" not in str(exc)


@pytest.mark.asyncio
async def test_sample_table_stats_returns_tracked_tables(env):
    async with env.maker() as db:
        sampled = await retention.sample_table_stats(db)
    # Postgres backend ⇒ every tracked table that exists is reported with a size.
    assert "workspaces" in sampled
    assert "llm_cost_events" in sampled
    size, _ = sampled["workspaces"]
    assert size is not None and size >= 0

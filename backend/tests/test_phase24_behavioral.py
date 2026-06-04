"""Phase 21 (Plan §24) behavioral pins — T-285.

The structural contract (`harness/tests/backend/test_phase24_github_living_contract.py`)
asserts shape; this file pins the *behaviors* it is deliberately lenient about,
plus the cross-cutting invariants enumerated in T-285.

Most of the named behavioral tests in T-285's "e.g." list already live in their
own domain files and are intentionally **not** duplicated here. Where to find them:

  - JWT / token provider / 401 re-mint  → test_github_app_auth.py,
    test_github_api_client_app.py
  - export 202 + idempotent/resumable    → test_github_integration.py
    (test_post_export_enqueues_and_returns_202), test_export_push_worker.py
    (test_run_export_push_is_idempotent_and_resumable)
  - webhook signature / rotation / dedup → test_webhook_ingest.py
  - reconcile by repo_id / confused-deputy / done_via / out-of-order
                                          → test_github_reconcile.py
  - backfill PR filter / refinalise drift → test_github_drift_backfill.py
  - pr_with_tests mode (branch/PR/403/409) → test_github_pr_export.py
  - AGENTS.md non-clobber                 → test_agent_issues.py
  - increment task_ref pinning / new-only sync
                                          → test_increment_generation.py,
    test_increment_sync.py
  - governor secondary-limit backoff      → test_github_governor.py

What this file adds is the set T-285 explicitly mandates as new pins, none of
which is covered above:

  1. The partial-unique-index predicate, pinned *behaviorally* (the contract is
     lenient on the predicate string): two non-`failed` pushes for the same
     `(workspace_id, repo_id)` collide; a `failed` row may coexist; and
     `find_live_push` resolves to the single live row.
  2. `task_ref` stability across a `T-NNN` renumber.
  3. Stuck-`pending` recovery: a crashed export is failed and the repo becomes
     re-exportable.
  4. The PR-diff evaluator is a *separate* component from `critic.py` and fails
     open (a judge error never bricks the check).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import (
    GitHubInstallation,
    IntegrationPush,
    IntegrationPushTask,
    Stage,
    StageVersion,
    User,
    Workspace,
)
from services.integrations import github_reconcile
from services.integrations.push_repo import find_live_push
from services.integrations.task_parser import compute_task_ref, parse_tasks

# asyncio_mode = "auto" (pyproject.toml) auto-detects the async tests; the one
# sync test in this module stays sync, so no module-level asyncio mark.


def _unique_numeric() -> int:
    return uuid4().int % 1_000_000_000


# ---------------------------------------------------------------------------
# Real-DB fixtures — the partial unique index is a Postgres feature, so these
# tests MUST run against the real database (SQLite would silently not enforce
# it and the integrity assertions would false-pass).
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


@pytest.fixture
async def user(session: AsyncSession) -> User:
    u = User(
        email=f"t285-{uuid4()}@example.com",
        google_id=f"g-{uuid4()}",
        name="Tester",
        avatar_url=None,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    user_id = u.id  # capture so teardown survives a test-side rollback (expiry)
    yield u
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


@pytest.fixture
async def workspace(session: AsyncSession, user: User) -> Workspace:
    ws = Workspace(
        user_id=user.id,
        name="WS",
        problem_statement="x" * 60,
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )
    session.add(ws)
    await session.commit()
    await session.refresh(ws)
    ws_id = ws.id  # capture so teardown survives a test-side rollback (expiry)
    yield ws
    await session.execute(delete(Workspace).where(Workspace.id == ws_id))
    await session.commit()


async def _make_install(session: AsyncSession, user: User) -> GitHubInstallation:
    inst = GitHubInstallation(
        installation_id=_unique_numeric(),
        account_login="octo",
        account_type="Organization",
        repository_selection="all",
        user_id=user.id,
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    return inst


def _push(
    *,
    workspace_id: Any,
    user_id: Any,
    installation_id: Any,
    repo_id: int,
    status: str,
) -> IntegrationPush:
    # Takes raw ids (not ORM objects) so it stays safe to call after a failed
    # commit + rollback, which expires loaded instances (accessing their
    # attributes would trigger lazy IO outside the async greenlet context).
    return IntegrationPush(
        workspace_id=workspace_id,
        user_id=user_id,
        provider="github",
        installation_id=installation_id,
        repo_id=repo_id,
        repo_full_name="octo/app",
        status=status,
    )


async def _cleanup(session: AsyncSession, installation_id: Any) -> None:
    await session.execute(
        delete(IntegrationPush).where(
            IntegrationPush.installation_id == installation_id
        )
    )
    await session.execute(
        delete(GitHubInstallation).where(GitHubInstallation.id == installation_id)
    )
    await session.commit()


# ===========================================================================
# 1. Partial unique index: one live push per repo (pinned behaviorally)
# ===========================================================================


async def test_two_non_failed_pushes_for_same_repo_raise_integrity_error(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """`uq_integration_push_workspace_repo_active WHERE status <> 'failed'`.

    The contract only checks the index exists with a lenient predicate; this
    proves the predicate actually serializes live pushes per repo. A second
    non-`failed` row for the same `(workspace_id, repo_id)` must collide, a
    `failed` row is allowed to coexist, and `find_live_push` returns the one
    live row.
    """
    inst = await _make_install(session, user)
    # Capture ids before any failing commit — a rollback expires loaded ORM
    # instances, after which attribute access would raise MissingGreenlet.
    ws_id, u_id, inst_id = workspace.id, user.id, inst.id
    repo_id = _unique_numeric()
    try:
        live = _push(
            workspace_id=ws_id,
            user_id=u_id,
            installation_id=inst_id,
            repo_id=repo_id,
            status="completed",
        )
        session.add(live)
        await session.commit()
        live_id = live.id

        # A second non-`failed` push for the same repo violates the partial index.
        clash = _push(
            workspace_id=ws_id,
            user_id=u_id,
            installation_id=inst_id,
            repo_id=repo_id,
            status="pending",
        )
        session.add(clash)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # A `failed` row is outside the predicate, so it may coexist.
        failed = _push(
            workspace_id=ws_id,
            user_id=u_id,
            installation_id=inst_id,
            repo_id=repo_id,
            status="failed",
        )
        session.add(failed)
        await session.commit()  # no IntegrityError

        # The live-push lookup still resolves to exactly the one non-failed row.
        found = await find_live_push(session, ws_id, repo_id)
        assert found is not None
        assert found.id == live_id
        assert found.status == "completed"
    finally:
        await _cleanup(session, inst_id)


async def test_stale_status_is_live_and_keeps_partial_index_engaged(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """`stale` is a *non-failed* (live) status — it still occupies the slot.

    A drift/disconnect leaves a `stale` push that `find_live_push` must keep
    returning, and a second live push for the repo must still be rejected until
    the stale one is failed. This pins the lifecycle note in T-265 that "all
    non-`failed` rows are live."
    """
    inst = await _make_install(session, user)
    ws_id, u_id, inst_id = workspace.id, user.id, inst.id
    repo_id = _unique_numeric()
    try:
        stale = _push(
            workspace_id=ws_id,
            user_id=u_id,
            installation_id=inst_id,
            repo_id=repo_id,
            status="stale",
        )
        session.add(stale)
        await session.commit()

        found = await find_live_push(session, ws_id, repo_id)
        assert found is not None and found.status == "stale"

        clash = _push(
            workspace_id=ws_id,
            user_id=u_id,
            installation_id=inst_id,
            repo_id=repo_id,
            status="pending",
        )
        session.add(clash)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
    finally:
        await _cleanup(session, inst_id)


# ===========================================================================
# 2. task_ref stability across a T-NNN renumber
# ===========================================================================


def test_task_ref_stable_when_T_NNN_renumbers() -> None:
    """A task whose `T-NNN` changes but whose title is unchanged keeps the same
    `task_ref`, so re-export/reconcile/increment sync UPDATE the same GitHub
    Issue instead of opening a duplicate (spec Assumption 23)."""
    before = (
        "### T-001: Set up project structure\n\n**Description:** scaffold.\n\n"
        "### T-002: Add billing\n\n**Description:** Stripe.\n"
    )
    # A later refinement inserts a task ahead of "Add billing", pushing its
    # number from T-002 to T-003 — the human ref moved, the content did not.
    after = (
        "### T-001: Set up project structure\n\n**Description:** scaffold.\n\n"
        "### T-002: Add health endpoint\n\n**Description:** /health.\n\n"
        "### T-003: Add billing\n\n**Description:** Stripe.\n"
    )

    before_tasks = {t.title: t for t in parse_tasks(before)}
    after_tasks = {t.title: t for t in parse_tasks(after)}

    billing_before = before_tasks["Add billing"]
    billing_after = after_tasks["Add billing"]

    # The human-readable ref genuinely renumbered...
    assert billing_before.ref == "T-002"
    assert billing_after.ref == "T-003"
    # ...but the content-derived matching key is identical across the renumber.
    assert compute_task_ref(billing_before.title) == compute_task_ref(
        billing_after.title
    )

    # And distinct titles still produce distinct refs (no accidental collision).
    refs = {compute_task_ref(t.title) for t in after_tasks.values()}
    assert len(refs) == len(after_tasks)


# ===========================================================================
# 3. Stuck-pending recovery → repo becomes re-exportable
# ===========================================================================


async def test_reconcile_drift_clears_stale_pending_push(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    """A `pending` push whose arq job no longer exists (a crashed export) is
    failed by the periodic sweep, so the partial unique index stops blocking
    re-export: `find_live_push` returns nothing and a fresh push for the same
    repo inserts cleanly."""
    inst = await _make_install(session, user)
    ws_id, u_id, inst_id = workspace.id, user.id, inst.id
    repo_id = _unique_numeric()
    try:
        stuck = _push(
            workspace_id=ws_id,
            user_id=u_id,
            installation_id=inst_id,
            repo_id=repo_id,
            status="pending",
        )
        session.add(stuck)
        await session.commit()
        stuck_id = stuck.id

        # Before recovery: the stuck push IS the live push and blocks re-export.
        assert (await find_live_push(session, ws_id, repo_id)) is not None

        async def job_gone(push_id: str) -> bool:
            return False  # arq has no record → the export crashed

        async def noop_enqueue(job: str, *args: Any) -> None:
            return None

        await github_reconcile.reconcile_drift(
            {}, db=session, enqueue_fn=noop_enqueue, is_job_alive=job_gone
        )

        await session.refresh(stuck)
        assert stuck.status == "failed"

        # The repo is now re-exportable: no live push, and a new one inserts
        # without tripping the partial unique index.
        assert (await find_live_push(session, ws_id, repo_id)) is None
        fresh = _push(
            workspace_id=ws_id,
            user_id=u_id,
            installation_id=inst_id,
            repo_id=repo_id,
            status="pending",
        )
        session.add(fresh)
        await session.commit()  # no IntegrityError — the slot was freed

        relived = await find_live_push(session, ws_id, repo_id)
        assert relived is not None and relived.id != stuck_id
    finally:
        await _cleanup(session, inst_id)


# ===========================================================================
# 4. The PR-diff evaluator is NOT the critic, and it fails open
# ===========================================================================

_PR_TASKS = (
    "# Tasks\n\n## Phase 1: Core\n\n"
    "### T-001: Add health endpoint\n\n"
    "**Description:** Expose a health check.\n\n"
    "**Acceptance criteria:**\n1. `GET /health` returns 200.\n"
)


class _StubCheckClient:
    """In-memory stub of the GitHubAPIClient PR-check surface.

    Mirrors the real two-call flow: ``post_check_run`` creates the in-progress
    check, ``update_check_run`` finalises it with a conclusion — so the
    fail-open ``neutral`` outcome is observable on the update path.
    """

    def __init__(self) -> None:
        self.diff: str | None = (
            "diff --git a/health.py b/health.py\n+def health(): return 'ok'\n"
        )
        self.pr: dict[str, Any] | None = {
            "head": {"sha": "deadbeef"},
            "body": "Closes #101",
        }
        self.check_runs: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self._counter = 900

    async def get_pull_request(self, repo: str, number: int) -> dict[str, Any] | None:
        return self.pr

    async def get_pull_request_diff(self, repo: str, number: int) -> str | None:
        return self.diff

    async def post_check_run(
        self,
        repo: str,
        *,
        name: str,
        head_sha: str,
        status: str,
        conclusion: str | None = None,
        title: str,
        summary: str,
    ) -> int | None:
        self._counter += 1
        self.check_runs.append({"id": self._counter, "conclusion": conclusion})
        return self._counter

    async def update_check_run(
        self,
        repo: str,
        check_run_id: int,
        *,
        status: str,
        conclusion: str | None = None,
        title: str,
        summary: str,
    ) -> int | None:
        self.updated.append({"id": check_run_id, "conclusion": conclusion})
        return check_run_id

    async def post_commit_status(
        self, repo: str, sha: str, *, state: str, context: str, description: str
    ) -> None:
        self.updated.append({"sha": sha, "conclusion": state})

    @property
    def final_conclusion(self) -> str | None:
        if self.updated:
            return self.updated[-1]["conclusion"]
        completed = [c for c in self.check_runs if c.get("conclusion") is not None]
        return completed[-1]["conclusion"] if completed else None


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self.store[key] = value

    async def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> None:
        return None


def _read_source(path: str | None) -> str:
    if not path:
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _assert_evaluator_is_not_the_critic() -> None:
    """Spec §4.14 D / T-282: the PR-diff evaluator is a *new* fail-open
    component, explicitly NOT `services/pipeline/critic.py`. They must be
    different modules with different entrypoints, and the evaluator must not be
    implemented in terms of the critic's quality-gate review."""
    from services.integrations import pr_evaluator
    from services.pipeline import critic

    assert pr_evaluator.__name__ != critic.__name__
    assert pr_evaluator.__file__ != critic.__file__
    # The evaluator's entrypoint is its own; it does not reuse critic_review.
    assert hasattr(pr_evaluator, "run_pr_check")
    assert getattr(pr_evaluator, "run_pr_check") is not getattr(
        critic, "critic_review", None
    )
    # The fail-open quality gate does not import the critic to do its judging.
    src = _read_source(pr_evaluator.__file__)
    assert "from services.pipeline.critic" not in src
    assert "import critic" not in src


@pytest.fixture
async def pr_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _seed_pr(db: AsyncSession) -> dict[str, Any]:
    user = User(
        email=f"prcheck-{uuid4()}@example.com",
        google_id=f"g-{uuid4()}",
        name="U",
        avatar_url=None,
        credit_balance=100,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    ws = Workspace(
        user_id=user.id,
        name="WS",
        problem_statement="x" * 60,
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)

    stage = Stage(
        workspace_id=ws.id,
        type="tasks",
        content=_PR_TASKS,
        status="finalised",
        current_version=1,
        finalised_at=datetime.now(UTC),
    )
    db.add(stage)
    await db.flush()
    db.add(
        StageVersion(stage_id=stage.id, version=1, content=_PR_TASKS, created_by="ai")
    )
    await db.commit()

    inst = GitHubInstallation(
        installation_id=_unique_numeric(),
        account_login="octo",
        account_type="Organization",
        repository_selection="all",
        user_id=user.id,
    )
    db.add(inst)
    await db.commit()
    await db.refresh(inst)

    push = IntegrationPush(
        workspace_id=ws.id,
        user_id=user.id,
        provider="github",
        installation_id=inst.id,
        repo_id=_unique_numeric(),
        repo_full_name="octo/app",
        export_mode="pr_with_tests",
        status="completed",
    )
    db.add(push)
    await db.commit()
    await db.refresh(push)

    db.add(
        IntegrationPushTask(
            push_id=push.id, task_ref="T-001", external_issue_number=101, state="open"
        )
    )
    await db.commit()
    return {"user": user, "workspace": ws, "install": inst, "push": push}


async def _teardown_pr(db: AsyncSession, seeded: dict[str, Any]) -> None:
    await db.execute(delete(Workspace).where(Workspace.id == seeded["workspace"].id))
    await db.execute(
        delete(GitHubInstallation).where(GitHubInstallation.id == seeded["install"].id)
    )
    await db.execute(delete(User).where(User.id == seeded["user"].id))
    await db.commit()


async def test_pr_evaluator_is_not_the_critic_and_fails_open(
    pr_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PR-diff evaluator is a separate component from `critic.py` AND it
    fails open: a judge-model error must NEVER brick a generation — the check is
    posted NEUTRAL and `run_pr_check` returns normally (does not raise)."""
    from services.integrations import pr_evaluator

    # (a) It is a distinct component, not the quality-gate critic.
    _assert_evaluator_is_not_the_critic()

    # (b) It fails open when the judge model errors.
    seeded = await _seed_pr(pr_session)
    stub, redis = _StubCheckClient(), _FakeRedis()

    calls: list[int] = []

    async def boom(
        *, system_prompt: str, user_prompt: str, provider: Any = None
    ) -> str:
        calls.append(1)
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr(pr_evaluator, "call_judge_model", boom)
    try:
        # Must not raise — fail-open is the whole point.
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=pr_session, client=stub, redis=redis
        )
        assert calls == [1]  # the judge was attempted
        assert stub.final_conclusion == "neutral"  # and the failure is non-blocking
    finally:
        await _teardown_pr(pr_session, seeded)

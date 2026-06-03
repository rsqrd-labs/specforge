"""Tests for the bidirectional-sync reconcile job (Phase 21 — T-272).

Table-driven, real-DB fixtures (migration applied) drive the worker-side
dispatcher: issue close/reopen/edit, PR-merge attribution, the confused-deputy
guard, and out-of-order safety. Resolution is on the immutable ``repo_id`` under
the matching installation; ``enqueue`` is injected so the fan-out routing
assertions need no live queue.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import (
    GitHubInstallation,
    GitHubWebhookEvent,
    IntegrationPush,
    IntegrationPushTask,
    User,
    Workspace,
)
from services.integrations import github_reconcile

pytestmark = pytest.mark.asyncio

_REPO_ID = 556677
_ISSUE_NUMBER = 41
_T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _unique_numeric() -> int:
    return uuid4().int % 1_000_000_000


async def _noop_enqueue(job: str, *args: Any) -> None:
    return None


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
        email=f"test-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Tester",
        avatar_url=None,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    yield u
    await session.execute(delete(User).where(User.id == u.id))
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
    yield ws
    await session.execute(delete(Workspace).where(Workspace.id == ws.id))
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


async def _make_push_with_task(
    session: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    installation: GitHubInstallation,
    repo_id: int = _REPO_ID,
    issue_number: int = _ISSUE_NUMBER,
) -> IntegrationPushTask:
    push = IntegrationPush(
        workspace_id=workspace.id,
        user_id=user.id,
        provider="github",
        installation_id=installation.id,
        repo_id=repo_id,
        repo_full_name="octo/app",
        status="completed",
    )
    session.add(push)
    await session.commit()
    await session.refresh(push)
    task = IntegrationPushTask(
        push_id=push.id,
        task_ref="task-abc",
        external_issue_number=issue_number,
        state="open",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def _cleanup(session: AsyncSession, inst: GitHubInstallation) -> None:
    # Pushes cascade-delete their tasks; the install FK has no cascade, so the
    # pushes must go first.
    await session.execute(
        delete(IntegrationPush).where(IntegrationPush.installation_id == inst.id)
    )
    await session.execute(
        delete(GitHubInstallation).where(GitHubInstallation.id == inst.id)
    )
    await session.commit()


def _issue_event(
    *,
    action: str,
    repo_id: int,
    installation_numeric: int,
    issue_number: int = _ISSUE_NUMBER,
    updated_at: datetime,
    repo_full_name: str = "octo/app",
) -> bytes:
    return json.dumps(
        {
            "action": action,
            "repository": {"id": repo_id, "full_name": repo_full_name},
            "installation": {"id": installation_numeric},
            "issue": {
                "number": issue_number,
                "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
            },
        }
    ).encode()


def _pr_merged_event(
    *,
    repo_id: int,
    installation_numeric: int,
    closes_issue: int = _ISSUE_NUMBER,
    pr_number: int = 7,
    merged_at: datetime,
) -> bytes:
    return json.dumps(
        {
            "action": "closed",
            "repository": {"id": repo_id, "full_name": "octo/app"},
            "installation": {"id": installation_numeric},
            "pull_request": {
                "number": pr_number,
                "merged": True,
                "merged_at": merged_at.isoformat().replace("+00:00", "Z"),
                "body": f"Implements the thing. Closes #{closes_issue}",
            },
        }
    ).encode()


# ---------------------------------------------------------------------------
# Acceptance-named tests
# ---------------------------------------------------------------------------


async def test_reconcile_resolves_by_repo_id_not_full_name(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    try:
        # Same repo_id but a *renamed* repo (different full_name) still resolves.
        raw = _issue_event(
            action="closed",
            repo_id=_REPO_ID,
            installation_numeric=inst.installation_id,
            updated_at=_T0,
            repo_full_name="octo/renamed-after-transfer",
        )
        await github_reconcile.reconcile_event(
            {}, "d1", "issues", raw, db=session, enqueue_fn=_noop_enqueue
        )
        await session.refresh(task)
        assert task.state == "done"
    finally:
        await _cleanup(session, inst)


async def test_issue_close_flips_task_done_with_correct_done_via(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    try:
        # A plain issue close → manual.
        await github_reconcile.reconcile_event(
            {},
            "d-close",
            "issues",
            _issue_event(
                action="closed",
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                updated_at=_T0,
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "done"
        assert task.done_via == "manual"
        assert task.done_at is not None

        # A merged PR that closes the same issue upgrades attribution → pr_merge.
        await github_reconcile.reconcile_event(
            {},
            "d-merge",
            "pull_request",
            _pr_merged_event(
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                merged_at=_T0 + timedelta(seconds=5),
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "done"
        assert task.done_via == "pr_merge"  # upgraded, never downgraded
    finally:
        await _cleanup(session, inst)


async def test_merged_pr_alone_sets_done_via_pr_merge(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    try:
        await github_reconcile.reconcile_event(
            {},
            "d-merge-only",
            "pull_request",
            _pr_merged_event(
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                merged_at=_T0,
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "done"
        assert task.done_via == "pr_merge"
    finally:
        await _cleanup(session, inst)


async def test_reconcile_confused_deputy_install_a_cannot_touch_workspace_b(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    # The workspace's push is under installation B.
    inst_b = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst_b
    )
    try:
        # An event for the same repo_id but from a DIFFERENT installation (A)
        # must not touch the push under installation B.
        wrong_numeric = inst_b.installation_id + 1
        await github_reconcile.reconcile_event(
            {},
            "d-evil",
            "issues",
            _issue_event(
                action="closed",
                repo_id=_REPO_ID,
                installation_numeric=wrong_numeric,
                updated_at=_T0,
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "open"  # untouched
        assert task.done_via is None
    finally:
        await _cleanup(session, inst_b)


async def test_out_of_order_reopen_does_not_regress_done_task(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    try:
        # Close at T0+10.
        await github_reconcile.reconcile_event(
            {},
            "d-close",
            "issues",
            _issue_event(
                action="closed",
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                updated_at=_T0 + timedelta(seconds=10),
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "done"

        # A late 'reopened' carrying an OLDER timestamp (T0) must be ignored.
        await github_reconcile.reconcile_event(
            {},
            "d-stale-reopen",
            "issues",
            _issue_event(
                action="reopened",
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                updated_at=_T0,
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "done"  # not regressed

        # A genuinely newer 'reopened' (T0+20) does reopen.
        await github_reconcile.reconcile_event(
            {},
            "d-fresh-reopen",
            "issues",
            _issue_event(
                action="reopened",
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                updated_at=_T0 + timedelta(seconds=20),
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "open"
        assert task.done_at is None
    finally:
        await _cleanup(session, inst)


# ---------------------------------------------------------------------------
# Dispatcher routing + processed/lag
# ---------------------------------------------------------------------------


async def test_dispatcher_routes_pr_open_and_check_suite_to_pr_check(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    enqueued: list[tuple[Any, ...]] = []

    async def fake_enqueue(job: str, *args: Any) -> None:
        enqueued.append((job, *args))

    try:
        pr_open = json.dumps(
            {
                "action": "opened",
                "repository": {"id": _REPO_ID, "full_name": "octo/app"},
                "installation": {"id": inst.installation_id},
                "pull_request": {"number": 9, "merged": False},
            }
        ).encode()
        await github_reconcile.reconcile_event(
            {},
            "d-pr-open",
            "pull_request",
            pr_open,
            db=session,
            enqueue_fn=fake_enqueue,
        )
        assert ("pr_check", str(task.push_id), 9) in enqueued

        check = json.dumps(
            {
                "action": "completed",
                "repository": {"id": _REPO_ID, "full_name": "octo/app"},
                "installation": {"id": inst.installation_id},
                "check_suite": {"pull_requests": [{"number": 9}]},
            }
        ).encode()
        await github_reconcile.reconcile_event(
            {}, "d-check", "check_suite", check, db=session, enqueue_fn=fake_enqueue
        )
        assert enqueued.count(("pr_check", str(task.push_id), 9)) == 2
        # An opened PR is not a completion.
        await session.refresh(task)
        assert task.state == "open"
    finally:
        await _cleanup(session, inst)


async def test_unknown_event_is_ignored(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    try:
        raw = json.dumps(
            {
                "action": "created",
                "repository": {"id": _REPO_ID},
                "installation": {"id": inst.installation_id},
            }
        ).encode()
        # Should not raise and should not touch the task.
        await github_reconcile.reconcile_event(
            {}, "d-unknown", "star", raw, db=session, enqueue_fn=_noop_enqueue
        )
        await session.refresh(task)
        assert task.state == "open"
    finally:
        await _cleanup(session, inst)


async def test_mark_processed_stamps_delivery_row(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    inst = await _make_install(session, user)
    # A push must exist so the delivery resolves to our install; the task object
    # itself is not asserted on here.
    await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    delivery_id = f"dlv-{uuid4()}"
    event_row = GitHubWebhookEvent(delivery_id=delivery_id, event_type="issues")
    session.add(event_row)
    await session.commit()
    try:
        await github_reconcile.reconcile_event(
            {},
            delivery_id,
            "issues",
            _issue_event(
                action="closed",
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                updated_at=_T0,
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(event_row)
        assert event_row.processed_at is not None
    finally:
        await session.execute(
            delete(GitHubWebhookEvent).where(
                GitHubWebhookEvent.delivery_id == delivery_id
            )
        )
        await session.commit()
        await _cleanup(session, inst)


async def test_edited_does_not_poison_gate_for_out_of_order_close(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    # An 'edited' (T0+30) must be a true no-op: a later-delivered but
    # earlier-timestamped 'closed' (T0) must still flip the task done.
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    try:
        await github_reconcile.reconcile_event(
            {},
            "d-edit",
            "issues",
            _issue_event(
                action="edited",
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                updated_at=_T0 + timedelta(seconds=30),
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "open"
        assert task.synced_at is None  # edit advanced nothing

        await github_reconcile.reconcile_event(
            {},
            "d-late-close",
            "issues",
            _issue_event(
                action="closed",
                repo_id=_REPO_ID,
                installation_numeric=inst.installation_id,
                updated_at=_T0,
            ),
            db=session,
            enqueue_fn=_noop_enqueue,
        )
        await session.refresh(task)
        assert task.state == "done"  # the earlier-timestamped close still applies
    finally:
        await _cleanup(session, inst)


async def test_installation_deleted_event_routes_to_lifecycle_handler(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    # An 'installation/deleted' delivery, dispatched through reconcile_event,
    # must reach the T-270 lifecycle handler: the install's pushes go stale and
    # the row is removed.
    inst = await _make_install(session, user)
    task = await _make_push_with_task(
        session, workspace=workspace, user=user, installation=inst
    )
    push_id = task.push_id
    raw = json.dumps(
        {"action": "deleted", "installation": {"id": inst.installation_id}}
    ).encode()
    await github_reconcile.reconcile_event(
        {}, "d-uninstall", "installation", raw, db=session, enqueue_fn=_noop_enqueue
    )
    # The push was staled + detached and the install row removed.
    push = (
        await session.execute(
            select(IntegrationPush).where(IntegrationPush.id == push_id)
        )
    ).scalar_one()
    assert push.status == "stale"
    assert push.installation_id is None
    gone = (
        await session.execute(
            select(GitHubInstallation).where(GitHubInstallation.id == inst.id)
        )
    ).scalar_one_or_none()
    assert gone is None
    # Cleanup the detached push.
    await session.execute(delete(IntegrationPush).where(IntegrationPush.id == push_id))
    await session.commit()

"""Tests for find_live_push — the single source of the "live push" definition
(T-266).

A live push is the one non-``failed`` IntegrationPush row for a
``(workspace_id, repo_id)`` pair. The partial unique index from migration 0016
guarantees at most one exists. Uses the real DB (migration already applied), as
the rest of the integration suite does.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import IntegrationPush, IntegrationPushTask, User, Workspace
from services.integrations.push_repo import find_live_push, list_user_live_exports

pytestmark = pytest.mark.asyncio


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
        name="Test WS",
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


async def _add_push(
    session: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    repo_id: int,
    status: str,
) -> IntegrationPush:
    push = IntegrationPush(
        workspace_id=workspace.id,
        user_id=user.id,
        provider="github",
        repo_id=repo_id,
        status=status,
    )
    session.add(push)
    await session.commit()
    await session.refresh(push)
    return push


async def test_returns_the_single_non_failed_row(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    repo_id = 9_000_001
    # A failed row coexists with the live one (the partial index excludes
    # failed rows, so this is allowed).
    await _add_push(
        session, workspace=workspace, user=user, repo_id=repo_id, status="failed"
    )
    live = await _add_push(
        session, workspace=workspace, user=user, repo_id=repo_id, status="completed"
    )

    found = await find_live_push(session, workspace.id, repo_id)
    assert found is not None
    assert found.id == live.id
    assert found.status == "completed"


@pytest.mark.parametrize("status", ["pending", "completed", "stale"])
async def test_treats_every_non_failed_status_as_live(
    session: AsyncSession, user: User, workspace: Workspace, status: str
) -> None:
    repo_id = 9_000_100 + hash(status) % 1000
    await _add_push(
        session, workspace=workspace, user=user, repo_id=repo_id, status=status
    )
    found = await find_live_push(session, workspace.id, repo_id)
    assert found is not None and found.status == status


async def test_returns_none_when_only_failed(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    repo_id = 9_000_002
    await _add_push(
        session, workspace=workspace, user=user, repo_id=repo_id, status="failed"
    )
    assert await find_live_push(session, workspace.id, repo_id) is None


async def test_scoped_to_repo_id(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    await _add_push(
        session, workspace=workspace, user=user, repo_id=9_000_003, status="completed"
    )
    # A different repo under the same workspace has no live push.
    assert await find_live_push(session, workspace.id, 9_000_999) is None


# ---------------------------------------------------------------------------
# list_user_live_exports — the account-wide exports hub feed.
# ---------------------------------------------------------------------------


async def _add_task(
    session: AsyncSession, *, push: IntegrationPush, task_ref: str, state: str
) -> None:
    session.add(
        IntegrationPushTask(
            push_id=push.id,
            task_ref=task_ref,
            external_issue_number=hash(task_ref) % 100_000,
            state=state,
        )
    )
    await session.commit()


async def test_lists_live_export_with_counts(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    push = await _add_push(
        session, workspace=workspace, user=user, repo_id=9_100_001, status="completed"
    )
    await _add_task(session, push=push, task_ref="task-a", state="done")
    await _add_task(session, push=push, task_ref="task-b", state="done")
    await _add_task(session, push=push, task_ref="task-c", state="open")

    rows = await list_user_live_exports(session, user.id)
    mine = [r for r in rows if r.push.id == push.id]
    assert len(mine) == 1
    row = mine[0]
    assert row.workspace_name == workspace.name
    assert row.total == 3
    assert row.shipped == 2


async def test_excludes_failed_only_workspace(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    await _add_push(
        session, workspace=workspace, user=user, repo_id=9_100_002, status="failed"
    )
    rows = await list_user_live_exports(session, user.id)
    assert all(r.push.workspace_id != workspace.id for r in rows)


async def test_one_row_per_workspace_prefers_newest(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    # An older baseline push and a newer (increment-style) push on distinct repo
    # ids — both non-failed — must collapse to a single, newest row.
    older = await _add_push(
        session, workspace=workspace, user=user, repo_id=9_100_003, status="completed"
    )
    newer = await _add_push(
        session, workspace=workspace, user=user, repo_id=9_100_004, status="stale"
    )
    rows = await list_user_live_exports(session, user.id)
    mine = [r for r in rows if r.push.workspace_id == workspace.id]
    assert len(mine) == 1
    assert mine[0].push.id in {older.id, newer.id}
    # created_at DESC tie-break resolves to the more recently inserted row.
    assert mine[0].push.id == newer.id


async def test_scoped_to_user(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    await _add_push(
        session, workspace=workspace, user=user, repo_id=9_100_005, status="completed"
    )
    other = User(
        email=f"other-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Other",
        avatar_url=None,
    )
    session.add(other)
    await session.commit()
    await session.refresh(other)
    try:
        rows = await list_user_live_exports(session, other.id)
        assert all(r.push.user_id == other.id for r in rows)
        assert all(r.push.workspace_id != workspace.id for r in rows)
    finally:
        await session.execute(delete(User).where(User.id == other.id))
        await session.commit()

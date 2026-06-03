"""Tests for the increment schema + models (Phase 21 — T-278).

Behavioural, against the real DB (migration applied): server-side defaults, the
``(workspace_id, sequence)`` uniqueness, and the ``ON DELETE SET NULL`` behaviour
of the deferred ``increment_id`` FKs wired in migration 0017 — deleting an
increment must NOT cascade-delete the push/task, only null their pointer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import (
    Increment,
    IncrementIdea,
    IntegrationPush,
    IntegrationPushTask,
    Stage,
    StageVersion,
    User,
    Workspace,
)

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
        email=f"inc-{uuid4()}@example.com",
        google_id=f"g-{uuid4()}",
        name="T",
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
        name="Inc WS",
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


async def test_increment_defaults_and_persistence(
    session: AsyncSession, workspace: Workspace
) -> None:
    inc = Increment(workspace_id=workspace.id, sequence=1, title="Add billing")
    session.add(inc)
    await session.commit()
    await session.refresh(inc)

    assert inc.id is not None
    assert inc.status == "draft"  # server default
    assert inc.baseline_version_ids == []  # server default '[]'::jsonb
    assert inc.created_at is not None and inc.updated_at is not None

    await session.execute(delete(Increment).where(Increment.id == inc.id))
    await session.commit()


async def test_increment_baseline_version_ids_roundtrip(
    session: AsyncSession, workspace: Workspace
) -> None:
    ids = [str(uuid4()), str(uuid4())]
    inc = Increment(
        workspace_id=workspace.id,
        sequence=2,
        title="Pin baseline",
        baseline_version_ids=ids,
    )
    session.add(inc)
    await session.commit()
    await session.refresh(inc)
    assert inc.baseline_version_ids == ids

    await session.execute(delete(Increment).where(Increment.id == inc.id))
    await session.commit()


async def test_workspace_sequence_is_unique(
    session: AsyncSession, workspace: Workspace
) -> None:
    a = Increment(workspace_id=workspace.id, sequence=5, title="First")
    session.add(a)
    await session.commit()
    a_id = a.id  # capture before the failing commit expires the instance

    dup = Increment(workspace_id=workspace.id, sequence=5, title="Clash")
    session.add(dup)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    await session.execute(delete(Increment).where(Increment.id == a_id))
    await session.commit()


async def test_increment_idea_defaults(
    session: AsyncSession, workspace: Workspace
) -> None:
    idea = IncrementIdea(
        workspace_id=workspace.id,
        source="github",
        external_ref="gh-issue:123",
        text="Add dark mode",
    )
    session.add(idea)
    await session.commit()
    await session.refresh(idea)

    assert idea.status == "open"  # server default
    assert idea.increment_id is None
    assert idea.source == "github"
    assert idea.text == "Add dark mode"

    await session.execute(delete(IncrementIdea).where(IncrementIdea.id == idea.id))
    await session.commit()


async def test_deleting_increment_nulls_idea_pointer(
    session: AsyncSession, workspace: Workspace
) -> None:
    inc = Increment(workspace_id=workspace.id, sequence=9, title="Batch")
    session.add(inc)
    await session.commit()
    await session.refresh(inc)

    idea = IncrementIdea(
        workspace_id=workspace.id,
        increment_id=inc.id,
        source="user",
        text="captured",
    )
    session.add(idea)
    await session.commit()

    # Deleting the increment must SET NULL the idea's pointer, not delete it.
    await session.execute(delete(Increment).where(Increment.id == inc.id))
    await session.commit()

    await session.refresh(idea)
    assert idea.increment_id is None  # reverted to the backlog, not removed

    await session.execute(delete(IncrementIdea).where(IncrementIdea.id == idea.id))
    await session.commit()


async def test_deleting_increment_nulls_push_and_task_pointers(
    session: AsyncSession, user: User, workspace: Workspace
) -> None:
    # Minimal finalised tasks stage so the push/task rows are realistic.
    stage = Stage(
        workspace_id=workspace.id,
        type="tasks",
        content="### T-001: x\n",
        status="finalised",
        current_version=1,
        finalised_at=datetime.now(UTC),
    )
    session.add(stage)
    await session.commit()
    await session.refresh(stage)
    sv = StageVersion(stage_id=stage.id, version=1, content="x", created_by="user")
    session.add(sv)
    await session.commit()

    inc = Increment(workspace_id=workspace.id, sequence=11, title="Delta")
    session.add(inc)
    await session.commit()
    await session.refresh(inc)

    push = IntegrationPush(
        workspace_id=workspace.id,
        user_id=user.id,
        provider="github",
        status="completed",
        increment_id=inc.id,
    )
    session.add(push)
    await session.commit()
    await session.refresh(push)

    task = IntegrationPushTask(
        push_id=push.id,
        task_ref="T-001",
        external_issue_number=1,
        increment_id=inc.id,
    )
    session.add(task)
    await session.commit()

    # Delete the increment → SET NULL on both pointers; the rows survive.
    await session.execute(delete(Increment).where(Increment.id == inc.id))
    await session.commit()

    await session.refresh(push)
    await session.refresh(task)
    assert push.increment_id is None
    assert task.increment_id is None
    assert (
        await session.execute(
            select(IntegrationPush).where(IntegrationPush.id == push.id)
        )
    ).scalar_one() is not None  # push not deleted

    await session.execute(delete(IntegrationPush).where(IntegrationPush.id == push.id))
    await session.execute(delete(Stage).where(Stage.id == stage.id))
    await session.commit()

"""PostgreSQL integration test for T-196 — finalise() SELECT FOR UPDATE.

Requires TEST_DATABASE_URL env var pointing to a live PostgreSQL instance.
Skip if not set (CI injects via T-204 services block).

Run with (set TEST_DATABASE_URL first)::

    uv run pytest tests/test_finalise_integration.py -v

Isolation-level note
--------------------
Under READ COMMITTED (PostgreSQL / asyncpg default), session B unblocks after
A commits and re-reads the row, seeing status='finalised'.  The SELECT FOR
UPDATE (with_for_update) row-level lock in _load_stage() serialises the two
concurrent sessions: only one succeeds; the other blocks at the DB level until
the winner commits, then reads the committed status and raises ValueError.

Without lock=True (the CF-1 bug): both sessions issue SELECT without FOR UPDATE,
both read status='draft' before either commits, both pass the guard, and both
succeed — len(results)==2.
With lock=True: session B blocks at SELECT FOR UPDATE until A commits, then
reads status='finalised' and raises ValueError — len(results)==1.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from models import Base
from models.stage import Stage
from models.user import User
from models.workspace import Workspace
from services.pipeline.stage_manager import StageManager

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — integration test skipped. "
        "Set to postgresql+asyncpg://postgres:postgres@localhost:5432/specforge_test "
        "to run against a real PostgreSQL instance."
    ),
)


@pytest_asyncio.fixture(scope="module")
async def db_engine():
    """Create engine + all tables; drop everything after the module's tests finish."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_data(db_engine):
    """Insert a User, Workspace, and draft Stage; clean up after the test."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    stage_id = uuid.uuid4()

    async with factory() as session:
        user = User(
            id=user_id,
            email=f"test-{user_id}@example.com",
            google_id=str(user_id),
            name="Test User",
            credit_balance=100,
        )
        workspace = Workspace(
            id=workspace_id,
            user_id=user_id,
            name="Test Workspace",
            # problem_statement constraint: char_length BETWEEN 50 AND 10000
            problem_statement=(
                "Integration test workspace — placeholder problem statement."
            ),
            provider="anthropic",
            model="claude-3-haiku",
            status="active",
        )
        # Use type="tasks" (last in STAGE_ORDER) so _get_next_stage returns None
        # immediately, keeping the test focused on the DB locking path.
        stage = Stage(
            id=stage_id,
            workspace_id=workspace_id,
            type="tasks",
            content="# Initial content",
            status="draft",
            current_version=1,
        )
        session.add_all([user, workspace, stage])
        await session.commit()

    yield user_id, workspace_id, stage_id

    async with factory() as session:
        await session.execute(delete(Stage).where(Stage.id == stage_id))
        await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_finalise_serialised_by_select_for_update(
    db_engine, seed_data
):
    """SELECT FOR UPDATE in finalise() serialises concurrent finalise calls.

    Two coroutines race to finalise the same stage via asyncio.gather().
    Because finalise() uses _load_stage(..., lock=True) — which emits
    SELECT ... FOR UPDATE (with_for_update) — PostgreSQL acquires a row-level
    lock: one session proceeds; the other blocks at the DB level until the
    first commits.  The blocked session then reads status='finalised' (READ
    COMMITTED) and raises ValueError.

    This test FAILS if lock=True is removed from finalise() because both
    sessions then read status='draft' simultaneously and both succeed,
    yielding len(results)==2.
    """
    user_id, workspace_id, stage_id = seed_data
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    # Inject a mock Redis so the test stays focused on DB locking.
    fake_redis = AsyncMock()
    manager = StageManager(redis_client=fake_redis)

    class _FakeUser:
        id = user_id

    user = _FakeUser()
    results: list[str] = []
    errors: list[str] = []

    async def try_finalise() -> None:
        async with factory() as session:
            try:
                stage = await manager.finalise(stage_id, user, session)
                results.append(stage.status)
            except ValueError as e:
                errors.append(str(e))

    # asyncio.gather interleaves the two coroutines at every await point.
    # Both reach `await db.execute(SELECT ... FOR UPDATE)` before either
    # commits.  PostgreSQL serialises via the row lock: one proceeds, one
    # blocks and re-reads the committed status.
    await asyncio.gather(try_finalise(), try_finalise())

    assert len(results) == 1, (
        f"Expected exactly 1 successful finalise (SELECT FOR UPDATE serialises "
        f"concurrent calls), got {len(results)}: {results}. "
        f"If lock=True is absent from finalise(), both sessions read "
        f"status='draft' before either commits and both succeed — this "
        f"assertion would fail with 2 results."
    )
    assert (
        results[0] == "finalised"
    ), f"Successful finalise must set status='finalised', got {results[0]!r}"
    assert len(errors) == 1, (
        f"Expected exactly 1 ValueError from the blocked session, "
        f"got {len(errors)}: {errors}"
    )
    assert "cannot be finalised" in errors[0], (
        f"ValueError message must indicate the stage cannot be finalised, "
        f"got: {errors[0]!r}"
    )

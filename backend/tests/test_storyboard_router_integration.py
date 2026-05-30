"""Real-PostgreSQL integration tests for the Storyboard router (Phase 20 — T-251).

These verify the ownership boundary (acceptance criterion #4) and the JSONB ->
dict serialization round-trip against a live database, neither of which the
fake-DB unit tests can prove. Requires TEST_DATABASE_URL; skipped otherwise (CI
injects it via the services block).

Run with TEST_DATABASE_URL pointing at a disposable Postgres database, e.g.
``postgresql+asyncpg://specforge:specforge@localhost:5432/specforge_test``::

    TEST_DATABASE_URL=... uv run pytest tests/test_storyboard_router_integration.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import Base, Storyboard, User, Workspace

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — integration test skipped. "
        "Set to postgresql+asyncpg://specforge:specforge@localhost:5432/specforge_test "
        "to run against a real PostgreSQL instance."
    ),
)


class _NoopRedis:
    async def eval(self, *args, **kwargs) -> int:
        return 1

    async def set(self, *args, **kwargs) -> bool:
        return True


# Function-scoped engine with NullPool: pytest-asyncio runs each test in its own
# event loop, and asyncpg connections are loop-bound, so a module-scoped engine
# would hand connections across loops. NullPool guarantees every checkout is a
# fresh connection on the active loop.
@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def seed(db_engine):
    """User A (no storyboards), User B owning one ready Storyboard."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    workspace_b = uuid.uuid4()
    storyboard_b = uuid.uuid4()

    async with factory() as session:
        session.add_all(
            [
                User(id=user_a, email=f"a-{user_a}@x.com", google_id=str(user_a)),
                User(id=user_b, email=f"b-{user_b}@x.com", google_id=str(user_b)),
                Workspace(
                    id=workspace_b,
                    user_id=user_b,
                    name="B Workspace",
                    problem_statement=(
                        "Integration workspace placeholder problem statement text."
                    ),
                    provider="anthropic",
                    model="claude-3-haiku",
                    status="active",
                ),
                Storyboard(
                    id=storyboard_b,
                    workspace_id=workspace_b,
                    user_id=user_b,
                    version=1,
                    status="ready",
                    title="B's Launch Keynote",
                    theme="indica",
                    content_json={"title": "B's Launch Keynote", "sections": []},
                    speaker_notes_md="# Notes",
                    demo_script_md="# Demo",
                    technical_appendix_md="# Appendix",
                    source_map_json={"hero": [{"source": "SPEC"}]},
                    source_stage_version_ids={"spec": str(uuid.uuid4())},
                ),
            ]
        )
        await session.commit()

    yield user_a, user_b, workspace_b, storyboard_b

    async with factory() as session:
        await session.execute(delete(Storyboard).where(Storyboard.id == storyboard_b))
        await session.execute(delete(Workspace).where(Workspace.id == workspace_b))
        await session.execute(delete(User).where(User.id.in_([user_a, user_b])))
        await session.commit()


def _app_for(db_engine, current_user: User) -> object:
    app = create_app(redis_client=_NoopRedis())
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_storyboard(db_engine, seed) -> None:
    """Acceptance #4: a non-owner gets 404, never 200/403."""
    user_a, _user_b, _ws, storyboard_b = seed
    app = _app_for(db_engine, User(id=user_a, email="a@x.com", google_id="a"))
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.get(f"/storyboards/{storyboard_b}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_reads_own_storyboard_with_jsonb_roundtrip(db_engine, seed) -> None:
    """The owner gets 200 and JSONB columns deserialize to dicts in the body."""
    _user_a, user_b, workspace_b, storyboard_b = seed
    app = _app_for(db_engine, User(id=user_b, email="b@x.com", google_id="b"))
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.get(f"/storyboards/{storyboard_b}")
        presenter = await client.get(f"/storyboards/{storyboard_b}/presenter")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(storyboard_b)
    assert body["workspace_id"] == str(workspace_b)
    assert body["content"] == {"title": "B's Launch Keynote", "sections": []}
    assert body["source_map"] == {"hero": [{"source": "SPEC"}]}
    # Privacy: immutable source version ids must never reach the response.
    assert "source_stage_version_ids" not in body

    assert presenter.status_code == 200
    assert presenter.json()["demo_script_md"] == "# Demo"


@pytest.mark.asyncio
async def test_user_a_sees_no_storyboards_in_their_own_workspace_scope(
    db_engine, seed
) -> None:
    """Listing B's workspace as A returns 404 (workspace not owned by A)."""
    user_a, _user_b, workspace_b, _sb = seed
    app = _app_for(db_engine, User(id=user_a, email="a@x.com", google_id="a"))
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.get(f"/workspaces/{workspace_b}/storyboards")
    assert resp.status_code == 404

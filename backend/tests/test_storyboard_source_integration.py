"""Real-PostgreSQL integration tests for the Storyboard source builder (T-252).

Verifies the actual SQL — owner-scoped workspace load, finalised-stage gating,
and ``StageVersion`` pinning by ``current_version`` (selecting the right row out
of multiple versions) — which the fake-DB unit tests cannot prove. Requires
TEST_DATABASE_URL; skipped otherwise (CI injects it).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from models import Base, Stage, StageVersion, User, Workspace
from services.pipeline.storyboard_source import (
    StoryboardStagesNotFinalisedError,
    StoryboardWorkspaceNotFoundError,
    build_storyboard_source,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set — integration test skipped.",
)

_PLAN_MD = """# Plan

## Architecture
FastAPI + PostgreSQL + Redis. React SPA frontend.

## Security Architecture
CSRF + Fernet-encrypted keys.

## Capacity Model
10k DAU, 50 RPS peak.

## STRIDE
Spoofing mitigated by OAuth.

## SLO
99.9% availability.

## FMEA
Provider outage -> circuit breaker.
"""

_ARTIFACTS = {
    "spec": "# Spec\n\n## Overview\nFinalised spec overview content.\n",
    "plan": _PLAN_MD,
    "harness": "# Harness\n\n## Coverage\n40 tests cover 40 requirements.\n",
    "tasks": "# Tasks\n\n## Must-have\n- T-1 MUST ship auth.\n",
}


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
    """A user + workspace with four finalised stages, each at current_version=2.

    Every stage has an older v1 version with different content so the test proves
    the builder pins v2 (current_version), not v1.
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    current_version_ids: dict[str, uuid.UUID] = {}

    async with factory() as session:
        session.add(
            User(id=user_id, email=f"u-{user_id}@x.com", google_id=str(user_id))
        )
        session.add(
            Workspace(
                id=workspace_id,
                user_id=user_id,
                name="Integration WS",
                problem_statement=(
                    "Build a generator. Reach me at leak@example.com here."
                ),
                provider="anthropic",
                model="claude-sonnet-4-6",
                status="active",
            )
        )
        for stage_type, content in _ARTIFACTS.items():
            stage_id = uuid.uuid4()
            session.add(
                Stage(
                    id=stage_id,
                    workspace_id=workspace_id,
                    type=stage_type,
                    content="MUTABLE STAGE.CONTENT — must not be used",
                    status="finalised",
                    current_version=2,
                )
            )
            session.add(
                StageVersion(
                    id=uuid.uuid4(),
                    stage_id=stage_id,
                    version=1,
                    content="OLD V1 CONTENT",
                    created_by="ai",
                )
            )
            current = StageVersion(
                id=uuid.uuid4(),
                stage_id=stage_id,
                version=2,
                content=content,
                created_by="ai",
            )
            session.add(current)
            current_version_ids[stage_type] = current.id
        await session.commit()

    yield user_id, workspace_id, current_version_ids

    async with factory() as session:
        await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_pins_current_versions_and_extracts_excerpts(db_engine, seed) -> None:
    user_id, workspace_id, current_ids = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        pkg = await build_storyboard_source(session, workspace_id, user_id)

    assert pkg.stage_versions == current_ids
    for content in pkg.artifacts.values():
        assert "OLD V1 CONTENT" not in content
        assert "MUTABLE STAGE.CONTENT" not in content
    # Priority PLAN evidence extracted.
    for source_id in (
        "PLAN:architecture",
        "PLAN:stride",
        "PLAN:fmea",
        "HARNESS:coverage",
    ):
        assert source_id in pkg.excerpts
    # Problem statement scrubbed.
    assert "leak@example.com" not in pkg.problem_statement


@pytest.mark.asyncio
async def test_non_finalised_stage_blocks(db_engine, seed) -> None:
    user_id, workspace_id, _ids = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        # Flip one stage to draft.
        result = await session.execute(
            select(Stage).where(Stage.workspace_id == workspace_id)
        )
        stages = result.scalars().all()
        next(s for s in stages if s.type == "plan").status = "draft"
        await session.commit()

    async with factory() as session:
        with pytest.raises(StoryboardStagesNotFinalisedError) as exc:
            await build_storyboard_source(session, workspace_id, user_id)
    assert exc.value.not_ready.get("plan") == "draft"


@pytest.mark.asyncio
async def test_other_users_workspace_is_not_found(db_engine, seed) -> None:
    _user_id, workspace_id, _ids = seed
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        with pytest.raises(StoryboardWorkspaceNotFoundError):
            await build_storyboard_source(session, workspace_id, uuid.uuid4())

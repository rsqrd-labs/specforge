"""HTTP route tests for the GitHub sync endpoints (Phase 21 — T-273).

Exercises GET /workspaces/{id}/sync and the resync/backfill 202 enqueues through
the full ASGI stack against the real DB, with ``enqueue`` patched so no live
queue is needed. Also covers two reconcile branches (arq-alive checker fallback,
projects_v2_item routing) directly.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from database import get_db, get_redis
from main import create_app
from middleware.auth import get_current_user
from models import (
    GitHubInstallation,
    IntegrationPush,
    IntegrationPushTask,
    User,
    Workspace,
)
from routers import workspace as workspace_router
from services.integrations import github_reconcile

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def eval(self, *args: Any) -> int:
        return 1


@pytest.fixture
async def engine():
    eng = create_async_engine(settings.database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(maker: async_sessionmaker, *, with_push: bool = True) -> dict[str, Any]:
    async with maker() as db:
        user = User(
            email=f"sync-{uuid4()}@example.com",
            google_id=f"g-{uuid4()}",
            name="U",
            avatar_url=None,
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
        out: dict[str, Any] = {"user": user, "workspace": ws, "install": None}
        if with_push:
            inst = GitHubInstallation(
                installation_id=uuid4().int % 1_000_000_000,
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
                repo_id=uuid4().int % 1_000_000_000,
                repo_full_name="octo/app",
                status="stale",
            )
            db.add(push)
            await db.commit()
            await db.refresh(push)
            db.add_all(
                [
                    IntegrationPushTask(
                        push_id=push.id,
                        task_ref="t1",
                        external_issue_number=1,
                        state="done",
                    ),
                    IntegrationPushTask(
                        push_id=push.id,
                        task_ref="t2",
                        external_issue_number=2,
                        state="open",
                    ),
                ]
            )
            await db.commit()
            out["install"] = inst
            out["push"] = push
        return out


async def _teardown(maker: async_sessionmaker, seeded: dict[str, Any]) -> None:
    async with maker() as db:
        if seeded.get("install") is not None:
            await db.execute(
                delete(IntegrationPush).where(
                    IntegrationPush.installation_id == seeded["install"].id
                )
            )
            await db.execute(
                delete(GitHubInstallation).where(
                    GitHubInstallation.id == seeded["install"].id
                )
            )
        await db.execute(
            delete(Workspace).where(Workspace.id == seeded["workspace"].id)
        )
        await db.execute(delete(User).where(User.id == seeded["user"].id))
        await db.commit()


def _build_app(engine, user: User, enqueue_fn: Any):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    redis = _FakeRedis()
    app = create_app(redis_client=redis)
    app.state.redis = redis

    async def _get_db():
        async with maker() as db:
            yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_current_user] = lambda: user
    return app


async def test_get_sync_returns_drift_and_completion(engine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded = await _seed(maker)
    app = _build_app(engine, seeded["user"], None)
    try:
        async with _client(app) as client:
            resp = await client.get(f"/workspaces/{seeded['workspace'].id}/sync")
        assert resp.status_code == 200
        body = resp.json()
        assert body["push_id"] == str(seeded["push"].id)
        assert body["out_of_sync"] is True  # push status is 'stale'
        assert body["shipped"] == 1 and body["total"] == 2
        # The response serialises the task issue number under its alias.
        assert {t["external_issue_number"] for t in body["tasks"]} == {1, 2}
    finally:
        await _teardown(maker, seeded)


async def test_get_sync_404_when_no_push(engine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded = await _seed(maker, with_push=False)
    app = _build_app(engine, seeded["user"], None)
    try:
        async with _client(app) as client:
            resp = await client.get(f"/workspaces/{seeded['workspace'].id}/sync")
        assert resp.status_code == 404
    finally:
        await _teardown(maker, seeded)


async def test_resync_resets_pending_and_enqueues_202(engine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded = await _seed(maker)
    enqueued: list[tuple[Any, ...]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> str:
        enqueued.append((job, *args, kwargs.get("job_id")))
        return "job-id"

    app = _build_app(engine, seeded["user"], fake_enqueue)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(workspace_router, "enqueue", fake_enqueue)
    try:
        async with _client(app) as client:
            resp = await client.post(
                f"/workspaces/{seeded['workspace'].id}/sync/resync"
            )
        assert resp.status_code == 202
        assert resp.json()["status"] == "pending"
        assert enqueued and enqueued[0][0] == "export_push"
        assert enqueued[0][1] == str(seeded["push"].id)
        assert enqueued[0][-1] == str(seeded["push"].id)  # job_id == push_id
    finally:
        monkey.undo()
        await _teardown(maker, seeded)


async def test_backfill_enqueues_202(engine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded = await _seed(maker)
    enqueued: list[tuple[Any, ...]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> str:
        enqueued.append((job, *args))
        return "job-id"

    app = _build_app(engine, seeded["user"], fake_enqueue)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(workspace_router, "enqueue", fake_enqueue)
    try:
        async with _client(app) as client:
            resp = await client.post(
                f"/workspaces/{seeded['workspace'].id}/sync/backfill"
            )
        assert resp.status_code == 202
        assert enqueued == [("backfill_repo", str(seeded["push"].id))]
    finally:
        monkey.undo()
        await _teardown(maker, seeded)


async def test_backfill_503_when_queue_unavailable(engine) -> None:
    from services.queue import QueueUnavailableError

    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded = await _seed(maker)

    async def boom(job: str, *args: Any, **kwargs: Any) -> str:
        raise QueueUnavailableError("down")

    app = _build_app(engine, seeded["user"], boom)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(workspace_router, "enqueue", boom)
    try:
        async with _client(app) as client:
            resp = await client.post(
                f"/workspaces/{seeded['workspace'].id}/sync/backfill"
            )
        assert resp.status_code == 503
    finally:
        monkey.undo()
        await _teardown(maker, seeded)


# ---------------------------------------------------------------------------
# Direct reconcile-branch coverage
# ---------------------------------------------------------------------------


async def test_arq_job_alive_checker_is_conservative_without_redis() -> None:
    checker = github_reconcile._arq_job_alive_checker(None)
    # No redis to consult → report alive so a real export is never falsely swept.
    assert await checker("any-push-id") is True


async def test_projects_v2_item_routes_to_projects_sync(engine) -> None:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    seeded = await _seed(maker)
    enqueued: list[tuple[Any, ...]] = []

    async def fake_enqueue(job: str, *args: Any) -> None:
        enqueued.append((job, *args))

    import json

    payload = json.dumps(
        {
            "action": "edited",
            "repository": {"id": seeded["push"].repo_id},
            "installation": {"id": seeded["install"].installation_id},
        }
    ).encode()
    try:
        async with maker() as db:
            await github_reconcile.reconcile_event(
                {},
                "d-proj",
                "projects_v2_item",
                payload,
                db=db,
                enqueue_fn=fake_enqueue,
            )
        assert ("projects_sync", str(seeded["push"].id)) in enqueued
    finally:
        await _teardown(maker, seeded)

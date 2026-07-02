from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import Stage, User, Workspace
from schemas.workspace import WorkspaceCreate
from services.workspace_service import WorkspaceService

_USER_ID = uuid4()
_USER = User(
    id=_USER_ID,
    email="workspace@example.com",
    google_id="google-workspace",
    name="Workspace User",
    avatar_url=None,
    created_at=datetime.now(UTC),
)


def _make_workspace(user_id=None, status="active", with_stages=True) -> Workspace:
    wid = uuid4()
    uid = user_id or uuid4()
    stages = []
    if with_stages:
        for i, st in enumerate(["spec", "plan", "harness", "tasks"]):
            stages.append(
                Stage(
                    id=uuid4(),
                    workspace_id=wid,
                    type=st,
                    status="draft" if st == "spec" else "locked",
                    content=None,
                    current_version=0,
                    review_gate_acknowledged=False,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    w = Workspace(
        id=wid,
        user_id=uid,
        name="My WS",
        problem_statement=(
            "I want to build a task management web app for teams to create "
            "projects, assign tasks, track status, and notify users."
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    w.stages = stages
    return w


class _FakeDB:
    def __init__(
        self,
        workspace: Workspace | None = None,
        requesting_user_id: UUID | None = None,
        active_count: int = 0,
    ) -> None:
        self._workspace = workspace
        self._requesting_user_id = requesting_user_id
        self._active_count = active_count
        self._added: list[Any] = []
        self._committed = False
        self._refreshed: list[Any] = []

    async def execute(self, statement: Any) -> "_FakeScalars":
        if "count" in str(statement).lower():
            return _FakeScalars(self._workspace, scalar_value=self._active_count)
        workspace = self._workspace
        if (
            workspace is not None
            and self._requesting_user_id is not None
            and workspace.user_id != self._requesting_user_id
        ):
            workspace = None
        return _FakeScalars(workspace)

    def add(self, instance: Any) -> None:
        if isinstance(instance, (Workspace, Stage)):
            if isinstance(instance, Workspace):
                if not hasattr(instance, "id") or instance.id is None:
                    instance.id = uuid4()
                self._workspace = instance
                self._workspace.stages = []
            elif isinstance(instance, Stage):
                if not hasattr(instance, "id") or instance.id is None:
                    instance.id = uuid4()
                if self._workspace:
                    self._workspace.stages.append(instance)
        self._added.append(instance)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self._committed = True

    async def refresh(self, instance: Any) -> None:
        self._refreshed.append(instance)


class _FakeScalars:
    def __init__(
        self, workspace: Workspace | None, scalar_value: int | None = None
    ) -> None:
        self._workspace = workspace
        self._scalar_value = scalar_value

    def scalar(self) -> int | None:
        return self._scalar_value

    def scalar_one_or_none(self) -> Workspace | None:
        return self._workspace

    def scalar_one(self) -> Workspace:
        assert self._workspace is not None
        return self._workspace

    def scalars(self) -> "_FakeScalars":
        return self

    def __iter__(self):
        if self._workspace is not None:
            yield self._workspace


class _NoopPipeline:
    def zremrangebyscore(self, *args: Any) -> "_NoopPipeline":
        return self

    def zadd(self, *args: Any) -> "_NoopPipeline":
        return self

    def zcard(self, *args: Any) -> "_NoopPipeline":
        return self

    def expire(self, *args: Any) -> "_NoopPipeline":
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _NoopRedis:
    async def eval(self, *args, **kwargs) -> int:
        return 1

    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


@pytest.fixture
def app():
    _app = create_app(redis_client=_NoopRedis())
    _app.dependency_overrides[get_current_user] = lambda: _USER
    return _app


@pytest.mark.asyncio
async def test_create_workspace_adds_four_stages() -> None:
    svc = WorkspaceService()
    db = _FakeDB()
    payload = WorkspaceCreate(
        name="Test",
        problem_statement=(
            "I want to build a task management web app for teams to create "
            "projects, assign tasks, track status, and notify users."
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    workspace = await svc.create(uuid4(), payload, db)
    stage_types = [s.type for s in workspace.stages]
    assert sorted(stage_types) == ["harness", "plan", "spec", "tasks"]


@pytest.mark.asyncio
async def test_create_workspace_spec_is_draft_others_locked() -> None:
    svc = WorkspaceService()
    db = _FakeDB()
    payload = WorkspaceCreate(
        name="Test",
        problem_statement=(
            "I want to build a task management web app for teams to create "
            "projects, assign tasks, track status, and notify users."
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    workspace = await svc.create(uuid4(), payload, db)
    statuses = {s.type: s.status for s in workspace.stages}
    assert statuses["spec"] == "draft"
    for t in ["plan", "harness", "tasks"]:
        assert statuses[t] == "locked"


@pytest.mark.asyncio
async def test_create_workspace_sanitizes_user_text() -> None:
    svc = WorkspaceService()
    db = _FakeDB()
    payload = WorkspaceCreate(
        name="<b>Test</b>",
        problem_statement=(
            "<script>alert('xss')</script>I want to build a task management web "
            "app for teams to create projects, assign tasks, track status, "
            "and notify users."
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    workspace = await svc.create(uuid4(), payload, db)
    assert workspace.name == "Test"
    assert "<script>" not in workspace.problem_statement
    assert "alert" not in workspace.problem_statement


@pytest.mark.asyncio
async def test_create_workspace_rejects_when_active_workspace_quota_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = WorkspaceService()
    db = _FakeDB(active_count=2)
    payload = WorkspaceCreate(
        name="Test",
        problem_statement=(
            "I want to build a task management web app for teams to create "
            "projects, assign tasks, track status, and notify users."
        ),
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    monkeypatch.setattr(
        "services.workspace_service.settings.max_active_workspaces_per_user",
        2,
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.create(uuid4(), payload, db)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == {"code": "workspace_quota_exceeded", "limit": 2}
    assert db._added == []


@pytest.mark.asyncio
async def test_get_workspace_not_found_raises_404() -> None:
    svc = WorkspaceService()
    db = _FakeDB(workspace=None)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get(uuid4(), uuid4(), db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_workspace_wrong_owner_raises_404() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    wrong_user_id = uuid4()
    db = _FakeDB(workspace=workspace, requesting_user_id=wrong_user_id)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get(workspace.id, wrong_user_id, db)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Workspace not found"


@pytest.mark.asyncio
async def test_update_workspace_wrong_owner_raises_404() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    wrong_user_id = uuid4()
    db = _FakeDB(workspace=workspace, requesting_user_id=wrong_user_id)
    with pytest.raises(HTTPException) as exc_info:
        await svc.update(workspace.id, wrong_user_id, "New Name", db)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Workspace not found"
    assert db._committed is False


@pytest.mark.asyncio
async def test_archive_workspace_wrong_owner_raises_404() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    wrong_user_id = uuid4()
    db = _FakeDB(workspace=workspace, requesting_user_id=wrong_user_id)
    with pytest.raises(HTTPException) as exc_info:
        await svc.archive(workspace.id, wrong_user_id, db)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Workspace not found"
    assert db._committed is False


@pytest.mark.asyncio
async def test_get_workspace_correct_owner_returns_workspace() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    db = _FakeDB(workspace=workspace, requesting_user_id=workspace.user_id)
    result = await svc.get(workspace.id, workspace.user_id, db)
    assert result.id == workspace.id


@pytest.mark.asyncio
async def test_update_workspace_name() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    db = _FakeDB(workspace=workspace)
    result = await svc.update(workspace.id, workspace.user_id, "New Name", db)
    assert result.name == "New Name"
    assert db._committed is True
    assert workspace in db._refreshed


@pytest.mark.asyncio
async def test_update_workspace_sanitizes_name() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    db = _FakeDB(workspace=workspace)
    result = await svc.update(workspace.id, workspace.user_id, "<i>Clean</i>", db)
    assert result.name == "Clean"


@pytest.mark.asyncio
async def test_archive_workspace_sets_status() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    db = _FakeDB(workspace=workspace)
    await svc.archive(workspace.id, workspace.user_id, db)
    assert workspace.status == "archived"
    assert db._committed is True


@pytest.mark.asyncio
async def test_archive_workspace_stamps_trash_clock_and_ack() -> None:
    # Issue #43: archive sets the purge clock and records the ack version the
    # delete dialog displayed (the acked short-window path).
    svc = WorkspaceService()
    workspace = _make_workspace()
    workspace.archived_at = None
    workspace.retention_ack_version = None
    db = _FakeDB(workspace=workspace)
    await svc.archive(workspace.id, workspace.user_id, db, ack_version="trash-v1")
    assert workspace.status == "archived"
    assert workspace.archived_at is not None
    assert workspace.retention_ack_version == "trash-v1"


@pytest.mark.asyncio
async def test_archive_workspace_without_ack_leaves_version_null() -> None:
    # A stale SPA that omits ack_version falls into the conservative legacy window.
    svc = WorkspaceService()
    workspace = _make_workspace()
    workspace.retention_ack_version = "stale"
    db = _FakeDB(workspace=workspace)
    await svc.archive(workspace.id, workspace.user_id, db)
    assert workspace.archived_at is not None
    assert workspace.retention_ack_version is None


@pytest.mark.asyncio
async def test_restore_workspace_clears_trash_clock() -> None:
    # Issue #43: restore flips archived → active and clears the purge clock so the
    # workspace is no longer eligible for hard-delete.
    svc = WorkspaceService()
    workspace = _make_workspace(status="archived")
    workspace.archived_at = datetime.now(UTC)
    workspace.retention_ack_version = "trash-v1"
    db = _FakeDB(workspace=workspace)
    restored = await svc.restore(workspace.id, workspace.user_id, db)
    assert restored.status == "active"
    assert restored.archived_at is None
    assert restored.retention_ack_version is None
    assert db._committed is True


@pytest.mark.asyncio
async def test_list_for_user_returns_workspaces() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    db = _FakeDB(workspace=workspace)
    result = await svc.list_for_user(workspace.user_id, db)
    assert len(result) == 1
    assert result[0].id == workspace.id


@pytest.mark.asyncio
async def test_get_workspace_route_wrong_owner_returns_404(app) -> None:
    workspace = _make_workspace()

    async def _fake_db():
        yield _FakeDB(workspace=workspace, requesting_user_id=_USER_ID)

    app.dependency_overrides[get_db] = _fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/workspaces/{workspace.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace not found"


@pytest.mark.asyncio
async def test_update_workspace_route_wrong_owner_returns_404(app) -> None:
    workspace = _make_workspace()

    async def _fake_db():
        yield _FakeDB(workspace=workspace, requesting_user_id=_USER_ID)

    app.dependency_overrides[get_db] = _fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/workspaces/{workspace.id}", json={"name": "New Name"}
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace not found"


@pytest.mark.asyncio
async def test_archive_workspace_route_wrong_owner_returns_404(app) -> None:
    workspace = _make_workspace()

    async def _fake_db():
        yield _FakeDB(workspace=workspace, requesting_user_id=_USER_ID)

    app.dependency_overrides[get_db] = _fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/workspaces/{workspace.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Workspace not found"


@pytest.mark.asyncio
async def test_trashed_route_is_not_shadowed_by_id_route(app) -> None:
    # Issue #43: GET /workspaces/trashed must resolve to the trash list, not to
    # GET /workspaces/{id} with id="trashed" (which would 422 on the UUID parse).
    workspace = _make_workspace(user_id=_USER_ID, status="archived")
    workspace.archived_at = datetime.now(UTC)
    workspace.retention_ack_version = "trash-v1"

    async def _fake_db():
        yield _FakeDB(workspace=workspace)

    app.dependency_overrides[get_db] = _fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/workspaces/trashed")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body and body[0]["id"] == str(workspace.id)
    assert body[0]["acknowledged"] is True
    assert "purge_after" in body[0]


@pytest.mark.asyncio
async def test_retention_policy_route_returns_windows(app) -> None:
    # Issue #43: the unauthenticated policy endpoint serves the live windows +
    # the ack version the delete dialog stamps.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/retention/policy")

    assert response.status_code == 200
    body = response.json()
    assert body["policy_version"] == "trash-v1"
    assert body["trash_days"] >= 1
    assert "stage_versions_keep" in body
    assert response.headers.get("Cache-Control", "").startswith("public")


# ---------------------------------------------------------------------------
# Problem-statement cap (compression plan Phase A §2). The request schemas must
# mirror the gate's bounds exactly, so a value the gate accepts is storable.
# ---------------------------------------------------------------------------


def test_create_schema_bounds_match_the_gate_constants() -> None:
    from pydantic import ValidationError

    from schemas.workspace import WorkspaceUpdate
    from services.security.problem_statement_gate import (
        PROBLEM_STATEMENT_MAX_CHARS,
        PROBLEM_STATEMENT_MIN_CHARS,
    )

    base = "I want to build a project tracker for teams to manage tasks. "
    at_cap = (base * (PROBLEM_STATEMENT_MAX_CHARS // len(base))).strip()
    assert len(at_cap) <= PROBLEM_STATEMENT_MAX_CHARS
    assert len(at_cap) > 10_000  # above the old ceiling

    # Accepted at the raised cap on both create and update.
    WorkspaceCreate(
        name="Big", problem_statement=at_cap, provider="anthropic", model=None
    )
    WorkspaceUpdate(problem_statement=at_cap)

    too_long = "a" * (PROBLEM_STATEMENT_MAX_CHARS + 1)
    with pytest.raises(ValidationError):
        WorkspaceCreate(
            name="Big", problem_statement=too_long, provider="anthropic", model=None
        )
    with pytest.raises(ValidationError):
        WorkspaceUpdate(problem_statement=too_long)

    too_short = "a" * (PROBLEM_STATEMENT_MIN_CHARS - 1)
    with pytest.raises(ValidationError):
        WorkspaceCreate(
            name="Small", problem_statement=too_short, provider="anthropic", model=None
        )

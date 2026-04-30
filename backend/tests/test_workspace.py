from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from models import Stage, Workspace
from schemas.workspace import WorkspaceCreate
from services.workspace_service import WorkspaceService


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
        problem_statement="A" * 60,
        provider="anthropic",
        model="claude-sonnet-4-6",
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    w.stages = stages
    return w


class _FakeDB:
    def __init__(self, workspace: Workspace | None = None) -> None:
        self._workspace = workspace
        self._added: list[Any] = []
        self._committed = False
        self._refreshed: list[Any] = []

    async def execute(self, statement: Any) -> "_FakeScalars":
        return _FakeScalars(self._workspace)

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
    def __init__(self, workspace: Workspace | None) -> None:
        self._workspace = workspace

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


@pytest.mark.asyncio
async def test_create_workspace_adds_four_stages() -> None:
    svc = WorkspaceService()
    db = _FakeDB()
    payload = WorkspaceCreate(
        name="Test",
        problem_statement="A" * 60,
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
        problem_statement="A" * 60,
        provider="anthropic",
        model="claude-sonnet-4-6",
    )
    workspace = await svc.create(uuid4(), payload, db)
    statuses = {s.type: s.status for s in workspace.stages}
    assert statuses["spec"] == "draft"
    for t in ["plan", "harness", "tasks"]:
        assert statuses[t] == "locked"


@pytest.mark.asyncio
async def test_get_workspace_not_found_raises_404() -> None:
    svc = WorkspaceService()
    db = _FakeDB(workspace=None)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get(uuid4(), uuid4(), db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_workspace_wrong_owner_raises_403() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    db = _FakeDB(workspace=workspace)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get(workspace.id, uuid4(), db)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_workspace_correct_owner_returns_workspace() -> None:
    svc = WorkspaceService()
    workspace = _make_workspace()
    db = _FakeDB(workspace=workspace)
    result = await svc.get(workspace.id, workspace.user_id, db)
    assert result.id == workspace.id

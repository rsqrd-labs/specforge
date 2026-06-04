"""Tests for the Projects v2 board + milestone sync (Phase 21 — T-281).

Two layers:

- **GraphQL client surface** (``httpx.MockTransport``, mirroring
  ``test_github_api_client_app.py``): ``graphql`` returns ``data`` on success but
  raises on a 200-with-``errors`` body, mapping a ``FORBIDDEN`` to the distinct
  ``GitHubProjectsPermissionError``; ``ensure_project_v2`` is find-then-create
  (no duplicate board on a re-run); status-field discovery + item add parse
  correctly; ``set_issue_milestone`` PATCHes (REST).
- **``sync_board`` service** (real DB + an in-memory stub client, mirroring
  ``test_increment_sync.py``): one milestone per ``## Phase`` heading with each
  task issue filed under it, every issue added to the board with its column set
  from ``open``/``done`` state, a missing **Projects** permission still applies
  the REST milestones, and the load-bearing invariant that a *failed* board sync
  never marks the shared baseline push ``failed``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
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
from services.integrations import github_projects
from services.integrations.github_api_client import (
    GitHubGraphQLError,
    GitHubProjectsPermissionError,
    make_app_github_client,
)

pytestmark = pytest.mark.asyncio


_PHASED_TASKS = (
    "# Tasks\n\n"
    "## Phase 1: Foundation\n\n"
    "### T-001: Set up project\n\n**Description:** Scaffold the repo.\n\n"
    "### T-002: Build the parser\n\n**Description:** Deterministic parser.\n\n"
    "## Phase 2: Core\n\n"
    "### T-003: Add billing\n\n**Description:** Stripe checkout.\n"
)


# ===========================================================================
# GraphQL client surface
# ===========================================================================


class _FakeTokenSource:
    async def get(self, installation_id: int) -> str:
        return "tok-1"

    async def refresh(self, installation_id: int) -> str:
        return "tok-2"


def _client(handler: Any):
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    return make_app_github_client(_FakeTokenSource(), 42, async_client)


async def test_graphql_returns_data_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graphql"
        return httpx.Response(200, json={"data": {"viewer": {"login": "octo"}}})

    client = _client(handler)
    data = await client.graphql("query{viewer{login}}")
    assert data == {"viewer": {"login": "octo"}}


async def test_graphql_raises_on_errors_array_despite_200() -> None:
    """GitHub answers 200 even on failure — a non-empty errors array must raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": None, "errors": [{"message": "Field 'x' doesn't exist"}]}
        )

    client = _client(handler)
    with pytest.raises(GitHubGraphQLError):
        await client.graphql("query{x}")


async def test_graphql_forbidden_maps_to_projects_permission_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": None,
                "errors": [
                    {
                        "type": "FORBIDDEN",
                        "message": "Resource not accessible by integration",
                    }
                ],
            },
        )

    client = _client(handler)
    with pytest.raises(GitHubProjectsPermissionError):
        await client.graphql("mutation{createProjectV2}")


async def test_add_project_v2_item_returns_item_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"addProjectV2ItemById": {"item": {"id": "item-9"}}}}
        )

    client = _client(handler)
    assert await client.add_project_v2_item("proj-1", "issue-node") == "item-9"


async def test_ensure_project_v2_reuses_existing_by_title() -> None:
    """A matching board title is reused — createProjectV2 is never sent."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        sent.append(body)
        # The discovery query lists the owner's boards; one already matches.
        return httpx.Response(
            200,
            json={
                "data": {
                    "node": {
                        "projectsV2": {
                            "nodes": [
                                {"id": "proj-existing", "title": "SpecForge — o/r"}
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            },
        )

    client = _client(handler)
    pid = await client.ensure_project_v2("owner-node", "SpecForge — o/r")
    assert pid == "proj-existing"
    assert len(sent) == 1  # only the discovery query, no create mutation
    assert "createProjectV2" not in sent[0]


async def test_ensure_project_v2_creates_when_missing() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:  # discovery: no match
            return httpx.Response(
                200,
                json={
                    "data": {
                        "node": {
                            "projectsV2": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                },
            )
        return httpx.Response(  # createProjectV2
            200, json={"data": {"createProjectV2": {"projectV2": {"id": "proj-new"}}}}
        )

    client = _client(handler)
    pid = await client.ensure_project_v2(
        "owner-node", "SpecForge — o/r", repository_id="repo-node"
    )
    assert pid == "proj-new"
    assert calls["n"] == 2


async def test_get_project_v2_status_field_parses_options() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "node": {
                        "field": {
                            "id": "field-status",
                            "options": [
                                {"id": "opt-todo", "name": "Todo"},
                                {"id": "opt-done", "name": "Done"},
                            ],
                        }
                    }
                }
            },
        )

    client = _client(handler)
    field_id, options = await client.get_project_v2_status_field("proj-1")
    assert field_id == "field-status"
    assert options == {"Todo": "opt-todo", "Done": "opt-done"}


async def test_set_issue_milestone_patches_rest() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={"number": 5})

    client = _client(handler)
    await client.set_issue_milestone("o/r", 5, 3)
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/repos/o/r/issues/5"
    assert seen["body"] == {"milestone": 3}


# ===========================================================================
# sync_board service
# ===========================================================================


class _StubClient:
    """In-memory stub of the GitHubAPIClient board surface."""

    def __init__(self) -> None:
        self.milestones: dict[str, int] = {}
        self.issue_milestones: dict[int, int] = {}
        self.board_items: dict[str, str] = {}  # content_id -> item_id
        self.item_status: dict[str, str] = {}  # item_id -> option_id
        self._milestone_counter = 0
        self.repo_node_error: Exception | None = None
        self.project_error: Exception | None = None

    async def ensure_milestone(
        self, repo: str, title: str, *, description: str | None = None
    ) -> int:
        if title not in self.milestones:
            self._milestone_counter += 1
            self.milestones[title] = self._milestone_counter
        return self.milestones[title]

    async def set_issue_milestone(
        self, repo: str, number: int, milestone: int | None
    ) -> None:
        self.issue_milestones[number] = milestone  # type: ignore[assignment]

    async def get_repo_node_ids(self, repo: str) -> tuple[str, str] | None:
        if self.repo_node_error is not None:
            raise self.repo_node_error
        return "repo-node", "owner-node"

    async def ensure_project_v2(
        self, owner_id: str, title: str, *, repository_id: str | None = None
    ) -> str | None:
        if self.project_error is not None:
            raise self.project_error
        return "proj-1"

    async def get_project_v2_status_field(self, project_id: str):
        return "field-status", {
            "Todo": "opt-todo",
            "In Progress": "opt-prog",
            "Done": "opt-done",
        }

    async def get_issue_node_id(self, repo: str, number: int) -> str | None:
        return f"issue-node-{number}"

    async def add_project_v2_item(self, project_id: str, content_id: str) -> str | None:
        item_id = self.board_items.get(content_id)
        if item_id is None:
            item_id = f"item-{content_id}"
            self.board_items[content_id] = item_id
        return item_id

    async def set_project_v2_item_status(
        self, project_id: str, item_id: str, field_id: str, option_id: str
    ) -> None:
        self.item_status[item_id] = option_id


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _seed(db: AsyncSession) -> dict[str, Any]:
    user = User(
        email=f"proj-{uuid4()}@example.com",
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

    for stage_type, content in (
        ("spec", "# Spec\n\nProduct."),
        ("plan", "# Plan\n\nPython FastAPI."),
        (
            "harness",
            "# Harness\n\n`harness/tests/test_api.py`\n```python\n"
            "def test_x():\n    assert True\n```\n",
        ),
        ("tasks", _PHASED_TASKS),
    ):
        stage = Stage(
            workspace_id=ws.id,
            type=stage_type,
            content=content,
            status="finalised",
            current_version=1,
            finalised_at=datetime.now(UTC),
        )
        db.add(stage)
        await db.flush()
        db.add(
            StageVersion(stage_id=stage.id, version=1, content=content, created_by="ai")
        )
    await db.commit()

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
        export_mode="files_to_default",
        status="completed",
    )
    db.add(push)
    await db.commit()
    await db.refresh(push)

    db.add_all(
        [
            IntegrationPushTask(
                push_id=push.id,
                task_ref="T-001",
                external_issue_number=101,
                state="done",
            ),
            IntegrationPushTask(
                push_id=push.id,
                task_ref="T-002",
                external_issue_number=102,
                state="open",
            ),
            IntegrationPushTask(
                push_id=push.id,
                task_ref="T-003",
                external_issue_number=103,
                state="open",
            ),
        ]
    )
    await db.commit()
    return {"user": user, "workspace": ws, "install": inst, "push": push}


async def _teardown(db: AsyncSession, seeded: dict[str, Any]) -> None:
    await db.execute(delete(Workspace).where(Workspace.id == seeded["workspace"].id))
    await db.execute(
        delete(GitHubInstallation).where(GitHubInstallation.id == seeded["install"].id)
    )
    await db.execute(delete(User).where(User.id == seeded["user"].id))
    await db.commit()


async def test_sync_board_creates_milestone_per_phase_and_assigns_issues(
    session: AsyncSession,
) -> None:
    seeded = await _seed(session)
    stub = _StubClient()
    try:
        await github_projects.sync_board(
            {}, str(seeded["push"].id), db=session, client=stub
        )

        # One milestone per phase heading.
        assert set(stub.milestones) == {"Phase 1: Foundation", "Phase 2: Core"}
        p1 = stub.milestones["Phase 1: Foundation"]
        p2 = stub.milestones["Phase 2: Core"]
        # Each issue filed under its phase milestone.
        assert stub.issue_milestones == {101: p1, 102: p1, 103: p2}
    finally:
        await _teardown(session, seeded)


async def test_sync_board_sets_columns_from_task_state(session: AsyncSession) -> None:
    seeded = await _seed(session)
    stub = _StubClient()
    try:
        await github_projects.sync_board(
            {}, str(seeded["push"].id), db=session, client=stub
        )

        # Every issue is on the board.
        assert set(stub.board_items) == {
            "issue-node-101",
            "issue-node-102",
            "issue-node-103",
        }
        # T-001 is done -> Done; T-002/T-003 open -> Todo.
        assert stub.item_status["item-issue-node-101"] == "opt-done"
        assert stub.item_status["item-issue-node-102"] == "opt-todo"
        assert stub.item_status["item-issue-node-103"] == "opt-todo"
    finally:
        await _teardown(session, seeded)


async def test_sync_board_is_idempotent(session: AsyncSession) -> None:
    """A re-run adds no duplicate milestones or board items."""
    seeded = await _seed(session)
    stub = _StubClient()
    try:
        await github_projects.sync_board(
            {}, str(seeded["push"].id), db=session, client=stub
        )
        await github_projects.sync_board(
            {}, str(seeded["push"].id), db=session, client=stub
        )
        assert set(stub.milestones) == {"Phase 1: Foundation", "Phase 2: Core"}
        assert len(stub.board_items) == 3  # one card per issue across two runs
    finally:
        await _teardown(session, seeded)


async def test_sync_board_permission_error_still_applies_milestones(
    session: AsyncSession,
) -> None:
    """A missing Projects permission skips the board but keeps the REST
    milestones — the job does not raise (board is opt-in/additive)."""
    seeded = await _seed(session)
    stub = _StubClient()
    stub.project_error = GitHubProjectsPermissionError("no Projects scope")
    try:
        await github_projects.sync_board(
            {}, str(seeded["push"].id), db=session, client=stub
        )
        # Milestones applied despite the board being unreachable.
        assert set(stub.milestones) == {"Phase 1: Foundation", "Phase 2: Core"}
        assert stub.issue_milestones  # issues filed under milestones
        assert not stub.board_items  # board itself was skipped
    finally:
        await _teardown(session, seeded)


async def test_failed_board_sync_keeps_baseline_push_alive(
    session: AsyncSession,
) -> None:
    """A non-permission board failure raises (for retry) but never marks the
    shared baseline push failed."""
    seeded = await _seed(session)
    stub = _StubClient()
    stub.project_error = GitHubGraphQLError("github graphql exploded")
    try:
        with pytest.raises(GitHubGraphQLError):
            await github_projects.sync_board(
                {}, str(seeded["push"].id), db=session, client=stub
            )
        await session.rollback()
        for obj in (
            seeded["push"],
            seeded["install"],
            seeded["user"],
            seeded["workspace"],
        ):
            await session.refresh(obj)
        # The milestones (run before the board) still landed; the push is untouched.
        assert seeded["push"].status == "completed"
    finally:
        await _teardown(session, seeded)


async def test_sync_board_noop_for_failed_push(session: AsyncSession) -> None:
    """A non-live (failed) push is skipped — no GitHub calls, no error."""
    seeded = await _seed(session)
    seeded["push"].status = "failed"
    await session.commit()
    stub = _StubClient()
    try:
        await github_projects.sync_board(
            {}, str(seeded["push"].id), db=session, client=stub
        )
        assert not stub.milestones
        assert not stub.board_items
    finally:
        await _teardown(session, seeded)


async def test_sync_board_skips_status_when_option_missing(
    session: AsyncSession,
) -> None:
    """If the board's Status field has no matching option, the card is still
    added but its column is left unset (no crash)."""
    seeded = await _seed(session)
    stub = _StubClient()

    async def _fields_without_matching_option(project_id: str):
        return "field-status", {"Backlog": "opt-backlog"}

    stub.get_project_v2_status_field = _fields_without_matching_option  # type: ignore[assignment]
    try:
        await github_projects.sync_board(
            {}, str(seeded["push"].id), db=session, client=stub
        )
        # Cards added, but no status set since no option matched.
        assert len(stub.board_items) == 3
        assert stub.item_status == {}
    finally:
        await _teardown(session, seeded)


async def test_trigger_board_sync_enqueues_keyed_job(monkeypatch) -> None:
    """The forward producer enqueues ``projects_sync`` under a push-namespaced id."""
    calls: list[tuple[Any, ...]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> str:
        calls.append((job, args, kwargs.get("job_id")))
        return "job-id"

    import services.queue as queue_module

    monkeypatch.setattr(queue_module, "enqueue", fake_enqueue)
    push_id = uuid4()
    await github_projects.trigger_board_sync(push_id)
    assert calls == [("projects_sync", (str(push_id),), f"projects-sync-{push_id}")]


async def test_trigger_board_sync_swallows_queue_failure(monkeypatch) -> None:
    """A queue outage must never fail the already-committed caller (fail-soft)."""

    async def boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("redis down")

    import services.queue as queue_module

    monkeypatch.setattr(queue_module, "enqueue", boom)
    # Does not raise.
    await github_projects.trigger_board_sync(uuid4())


async def test_group_tasks_by_phase_without_headings() -> None:
    """Tasks with no ``## Phase`` heading bucket under a single ``None`` phase."""
    content = (
        "# Tasks\n\n### T-001: A\n\n**Description:** x.\n\n"
        "### T-002: B\n\n**Description:** y.\n"
    )
    grouped = github_projects._group_tasks_by_phase(content)
    assert len(grouped) == 1
    phase, tasks = grouped[0]
    assert phase is None
    assert [t.ref for t in tasks] == ["T-001", "T-002"]
    # Empty content yields no groups at all.
    assert github_projects._group_tasks_by_phase("") == []

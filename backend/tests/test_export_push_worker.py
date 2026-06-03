"""Tests for the App-mode export job (Phase 21 — T-269).

Covers the worker job body ``run_export_push``: it persists the three
loop-critical fields (``repo_id``, ``installation_id``,
``source_stage_version_id``), completes the push, and is idempotent/resumable —
a re-run never re-creates the repo or duplicates issues. Uses the real DB (the
migration is applied) with a stub GitHub client, mirroring
``test_github_export_service.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
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
from services.integrations.github_api_client import (
    GitHubAPIError,
    GitHubNotConnectedError,
)
from services.pipeline.github_export_service import (
    load_owned_installation,
    prepare_export_push,
    run_export_push,
)

pytestmark = pytest.mark.asyncio


_HARNESS_CONTENT = """\
## File: harness/tests/test_x.py

```python
def test_x() -> None:
    assert True
```
"""

_TASKS_CONTENT = """\
### T-001: First task

**Description:** Do thing one.

### T-002: Second task

**Description:** Do thing two.
"""


class _StubClient:
    """Records every GitHub call; create_repo returns a numeric id (repo_id)."""

    def __init__(self) -> None:
        self.created_repos: list[tuple[str, bool]] = []
        self.upserted_files: list[tuple[str, str, str | None]] = []
        self.issues_created: list[tuple[str, str]] = []
        self.issues_updated: list[tuple[int, str]] = []
        self.shas: dict[str, str] = {}
        self._issue_counter = 100

    async def create_repo(self, name: str, private: bool) -> dict[str, Any]:
        self.created_repos.append((name, private))
        return {
            "full_name": f"octocat/{name}",
            "html_url": f"https://github.com/octocat/{name}",
            "id": 556677,
        }

    async def get_file_sha(
        self, repo: str, path: str, *, ref: str | None = None
    ) -> str | None:
        return self.shas.get(path)

    async def get_file_content(
        self, repo: str, path: str, *, ref: str | None = None
    ) -> tuple[str, str] | None:
        return None  # AGENTS.md does not exist yet in these tests

    async def upsert_file(
        self,
        repo: str,
        path: str,
        content: str,
        sha: str | None,
        commit_message: str,
        *,
        branch: str | None = None,
    ) -> None:
        self.upserted_files.append((repo, path, sha))

    async def create_issue(
        self, repo: str, title: str, body: str, *, labels=None
    ) -> int:
        self.issues_created.append((title, body))
        self._issue_counter += 1
        return self._issue_counter

    async def update_issue(
        self, repo: str, number: int, title: str, body: str, *, labels=None
    ) -> None:
        self.issues_updated.append((number, title))


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
    for stage_type, content in (
        ("spec", "# spec"),
        ("plan", "# plan"),
        ("harness", _HARNESS_CONTENT),
        ("tasks", _TASKS_CONTENT),
    ):
        stage = Stage(
            workspace_id=ws.id,
            type=stage_type,
            content=content,
            status="finalised",
            current_version=1,
            finalised_at=datetime.now(UTC),
        )
        session.add(stage)
        await session.commit()
        await session.refresh(stage)
        # A StageVersion so source_stage_version_id resolves for the Tasks stage.
        session.add(
            StageVersion(
                stage_id=stage.id,
                version=1,
                content=content,
                created_by="user",
            )
        )
    await session.commit()
    yield ws
    await session.execute(delete(Workspace).where(Workspace.id == ws.id))
    await session.commit()


@pytest.fixture
async def installation(session: AsyncSession, user: User) -> GitHubInstallation:
    # A per-test installation_id (GitHub's numeric id is UNIQUE) so parallel /
    # repeated runs never collide.
    inst = GitHubInstallation(
        installation_id=uuid4().int % 1_000_000_000,
        account_login="octo-org",
        account_type="Organization",
        repository_selection="selected",
        user_id=user.id,
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    yield inst
    # Delete dependent pushes first — integration_pushes.installation_id has no
    # ON DELETE cascade, so the installation cannot be removed while referenced.
    await session.execute(
        delete(IntegrationPush).where(IntegrationPush.installation_id == inst.id)
    )
    await session.execute(
        delete(GitHubInstallation).where(GitHubInstallation.id == inst.id)
    )
    await session.commit()


async def _count_tasks(session: AsyncSession, push_id: Any) -> int:
    rows = (
        (
            await session.execute(
                select(IntegrationPushTask).where(
                    IntegrationPushTask.push_id == push_id
                )
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


async def test_run_export_push_persists_three_fields_and_completes(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    assert push.status == "pending"
    assert push.installation_id == installation.id

    stub = _StubClient()
    result = await run_export_push(
        push.id, "my-export", "private", db=session, client=stub
    )

    assert result is not None
    assert result.status == "completed"
    # The three loop-critical fields are persisted.
    assert result.repo_id == 556677
    assert result.installation_id == installation.id
    assert result.source_stage_version_id is not None
    assert result.repo_full_name == "octocat/my-export"
    assert len(stub.created_repos) == 1
    assert len(stub.issues_created) == 2
    assert await _count_tasks(session, push.id) == 2


async def test_run_export_push_is_idempotent_and_resumable(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )

    # First run completes the export.
    first = _StubClient()
    await run_export_push(push.id, "proj", "private", db=session, client=first)
    assert len(first.created_repos) == 1
    assert len(first.issues_created) == 2

    # Simulate a duplicate at-least-once delivery: reset to pending and re-run.
    # The repo already has a full_name and the two tasks are recorded, so the
    # re-run must NOT create a second repo or duplicate issues — it updates.
    push.status = "pending"
    await session.commit()

    second = _StubClient()
    second.shas = {"SPEC.md": "s1", "PLAN.md": "s2", "TASKS.md": "s3"}
    result = await run_export_push(
        push.id, "proj", "private", db=session, client=second
    )

    assert result is not None and result.status == "completed"
    assert second.created_repos == []  # no second repo
    assert second.issues_created == []  # no duplicate issues
    assert len(second.issues_updated) == 2  # existing issues updated instead
    assert await _count_tasks(session, push.id) == 2  # still exactly two


async def test_run_export_push_completed_is_noop(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    await run_export_push(push.id, "proj", "private", db=session, client=_StubClient())

    # A re-run of an already-completed push does nothing (at-least-once safe).
    noop_client = _StubClient()
    result = await run_export_push(
        push.id, "proj", "private", db=session, client=noop_client
    )
    assert result is not None and result.status == "completed"
    assert noop_client.created_repos == []
    assert noop_client.issues_created == []


class _FailingClient(_StubClient):
    async def create_repo(self, name: str, private: bool) -> dict[str, Any]:
        raise GitHubAPIError(500, "boom")


async def test_run_export_push_failure_marks_push_failed(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    with pytest.raises(GitHubAPIError):
        await run_export_push(
            push.id, "proj", "private", db=session, client=_FailingClient()
        )
    await session.refresh(push)
    # v2 'failed' so find_live_push (status <> 'failed') excludes it.
    assert push.status == "failed"


async def test_run_export_push_missing_installation_fails(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    # Clear the bound installation (e.g. uninstalled mid-flight) so the worker
    # resolves no installation for this push.
    push.installation_id = None
    await session.commit()

    with pytest.raises(GitHubNotConnectedError):
        await run_export_push(
            push.id, "proj", "private", db=session, client=_StubClient()
        )
    await session.refresh(push)
    assert push.status == "failed"


async def test_load_owned_installation_enforces_ownership(
    session: AsyncSession,
    user: User,
    installation: GitHubInstallation,
) -> None:
    # Owner: returns the installation.
    found = await load_owned_installation(session, installation.id, user.id)
    assert found is not None and found.id == installation.id

    # Another tenant: confused-deputy guard returns None.
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
        assert await load_owned_installation(session, installation.id, other.id) is None
        # Missing installation id: None.
        assert await load_owned_installation(session, uuid4(), user.id) is None
    finally:
        await session.execute(delete(User).where(User.id == other.id))
        await session.commit()

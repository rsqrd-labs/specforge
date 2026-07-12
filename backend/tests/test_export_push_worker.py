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
    GitHubRepoCreationUnsupportedError,
    GitHubRepoExistsError,
)
from services.pipeline.github_export_service import (
    installation_can_create_repos,
    list_repos_for_installation,
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
    """Records every GitHub call; create_org_repo returns a numeric id (repo_id)."""

    def __init__(self) -> None:
        self.created_repos: list[tuple[str, bool]] = []
        self.upserted_files: list[tuple[str, str, str | None]] = []
        self.issues_created: list[tuple[str, str]] = []
        self.issues_updated: list[tuple[int, str]] = []
        self.shas: dict[str, str] = {}
        self._issue_counter = 100

    async def get_repo(self, owner_repo: str) -> dict[str, Any] | None:
        return None  # repo doesn't exist yet, by default

    async def list_installation_repositories(
        self, **kwargs: Any
    ) -> tuple[list[dict[str, Any]], bool]:
        return [], False  # "selected" installs resolve against this grant list

    async def create_org_repo(
        self, org: str, name: str, private: bool
    ) -> dict[str, Any]:
        self.created_repos.append((name, private))
        return {
            "full_name": f"{org}/{name}",
            "html_url": f"https://github.com/{org}/{name}",
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
        repository_selection="all",
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
    assert result.repo_full_name == "octo-org/my-export"
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
    async def create_org_repo(
        self, org: str, name: str, private: bool
    ) -> dict[str, Any]:
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


async def test_run_export_push_transient_failure_stays_live_when_not_final_attempt(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    """A transient GitHubAPIError on a non-final attempt must NOT mark 'failed'.

    Regression for the premature "GitHub export failed" bug: the arq wrapper
    (services/queue.py) is about to retry this same job, so the push row must
    stay live (not 'failed') so the frontend's poll keeps waiting instead of
    reporting a terminal error for a hiccup the system itself expects to retry.
    """
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    with pytest.raises(GitHubAPIError):
        await run_export_push(
            push.id,
            "proj",
            "private",
            db=session,
            client=_FailingClient(),
            is_final_attempt=False,
        )
    await session.refresh(push)
    assert push.status == "pending"


async def test_run_export_push_transient_failure_then_retry_succeeds(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    """End-to-end: a non-final transient failure never blocks a later success.

    Simulates the real arq sequence — attempt 1 hits a transient error
    (is_final_attempt=False, push stays 'pending'), attempt 2 (the retry)
    succeeds against a healthy client and the push completes normally.
    """
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    with pytest.raises(GitHubAPIError):
        await run_export_push(
            push.id,
            "proj",
            "private",
            db=session,
            client=_FailingClient(),
            is_final_attempt=False,
        )
    await session.refresh(push)
    assert push.status == "pending"

    result = await run_export_push(
        push.id, "proj", "private", db=session, client=_StubClient()
    )
    assert result is not None
    assert result.status == "completed"


async def test_run_export_push_transient_failure_fails_on_final_attempt(
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
            push.id,
            "proj",
            "private",
            db=session,
            client=_FailingClient(),
            is_final_attempt=True,
        )
    await session.refresh(push)
    assert push.status == "failed"


class _RepoExistsClient(_StubClient):
    async def create_org_repo(
        self, org: str, name: str, private: bool
    ) -> dict[str, Any]:
        raise GitHubRepoExistsError(f"{name} already exists")


async def test_run_export_push_permanent_error_fails_even_on_non_final_attempt(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    """A deterministic error (taken repo name) fails immediately regardless of
    the retry budget — retrying the identical job can never succeed, so there
    is nothing worth waiting for."""
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    with pytest.raises(GitHubRepoExistsError):
        await run_export_push(
            push.id,
            "taken-name",
            "private",
            db=session,
            client=_RepoExistsClient(),
            is_final_attempt=False,
        )
    await session.refresh(push)
    assert push.status == "failed"


async def test_run_export_push_unsupported_creation_fails_fast(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
) -> None:
    """A personal (User) account, or any "selected repositories" install, has
    no App-compatible way to create a repo that doesn't exist yet — this must
    fail on the very first attempt (no retries) without ever calling
    create_org_repo."""
    inst = GitHubInstallation(
        installation_id=uuid4().int % 1_000_000_000,
        account_login="a-user",
        account_type="User",
        repository_selection="selected",
        user_id=user.id,
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    try:
        push = await prepare_export_push(
            session,
            workspace_id=workspace.id,
            user_id=user.id,
            installation=inst,
            export_mode="files_to_default",
        )
        client = _StubClient()
        with pytest.raises(GitHubRepoCreationUnsupportedError):
            await run_export_push(
                push.id,
                "new-repo",
                "private",
                db=session,
                client=client,
                is_final_attempt=False,
            )
        await session.refresh(push)
        assert push.status == "failed"
        assert client.created_repos == []
    finally:
        await session.execute(
            delete(IntegrationPush).where(IntegrationPush.installation_id == inst.id)
        )
        await session.execute(
            delete(GitHubInstallation).where(GitHubInstallation.id == inst.id)
        )
        await session.commit()


class _ExistingRepoClient(_StubClient):
    async def get_repo(self, owner_repo: str) -> dict[str, Any] | None:
        return {
            "full_name": owner_repo,
            "html_url": f"https://github.com/{owner_repo}",
            "id": 998877,
        }


async def test_run_export_push_skips_creation_when_repo_already_exists(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
    installation: GitHubInstallation,
) -> None:
    """An "all repositories" install is granted everything under its account,
    so a plain get_repo hit resolves the existing repo — export uses it
    directly instead of attempting creation."""
    push = await prepare_export_push(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        installation=installation,
        export_mode="files_to_default",
    )
    client = _ExistingRepoClient()
    result = await run_export_push(
        push.id, "already-there", "private", db=session, client=client
    )
    assert result is not None and result.status == "completed"
    assert result.repo_full_name == "octo-org/already-there"
    assert result.repo_id == 998877
    assert client.created_repos == []


class _GrantListClient(_StubClient):
    """Client for a "selected repositories" install: the grant list holds the
    target; get_repo must never be consulted (its `permissions` block is
    all-false under an installation token and a 200 doesn't prove a grant)."""

    async def list_installation_repositories(
        self, **kwargs: Any
    ) -> tuple[list[dict[str, Any]], bool]:
        return (
            [
                {
                    "id": 445566,
                    "name": "Granted-Repo",
                    "full_name": "a-user/Granted-Repo",
                    "html_url": "https://github.com/a-user/Granted-Repo",
                }
            ],
            False,
        )

    async def get_repo(self, owner_repo: str) -> dict[str, Any] | None:
        raise AssertionError(
            "selected-repositories installs must resolve via the grant list, "
            "never get_repo"
        )


async def test_run_export_push_selected_install_resolves_via_grant_list(
    session: AsyncSession,
    user: User,
    workspace: Workspace,
) -> None:
    """A personal/"selected" install exports into a granted existing repo by
    resolving it (case-insensitively) from GET /installation/repositories —
    the fix for the live failure where get_repo's all-false permissions block
    made every accessible repo look unusable."""
    inst = GitHubInstallation(
        installation_id=uuid4().int % 1_000_000_000,
        account_login="a-user",
        account_type="User",
        repository_selection="selected",
        user_id=user.id,
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    try:
        push = await prepare_export_push(
            session,
            workspace_id=workspace.id,
            user_id=user.id,
            installation=inst,
            export_mode="files_to_default",
        )
        client = _GrantListClient()
        result = await run_export_push(
            push.id, "granted-repo", "private", db=session, client=client
        )
        assert result is not None and result.status == "completed"
        assert result.repo_full_name == "a-user/Granted-Repo"
        assert result.repo_id == 445566
        assert client.created_repos == []
    finally:
        await session.execute(
            delete(IntegrationPush).where(IntegrationPush.installation_id == inst.id)
        )
        await session.execute(
            delete(GitHubInstallation).where(GitHubInstallation.id == inst.id)
        )
        await session.commit()


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


# ---------------------------------------------------------------------------
# Repo-picker service surface (installation_can_create_repos /
# list_repos_for_installation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account_type", "repository_selection", "expected"),
    [
        ("Organization", "all", True),
        ("Organization", "selected", False),
        ("User", "all", False),
        ("User", "selected", False),
    ],
)
def test_installation_can_create_repos_gate(
    account_type: str, repository_selection: str, expected: bool
) -> None:
    """The single create gate _run_app_export and the picker endpoint share:
    only an Organization installation scoped to all repositories can create."""
    inst = GitHubInstallation(
        installation_id=1,
        account_login="octo",
        account_type=account_type,
        repository_selection=repository_selection,
        user_id=uuid4(),
    )
    assert installation_can_create_repos(inst) is expected


async def test_list_repos_for_installation_uses_injected_client() -> None:
    """The injectable-client seam mirrors run_export_push: tests never build a
    real token provider / httpx client."""

    sentinel_rows = [{"id": 7, "name": "alpha", "full_name": "octo/alpha"}]

    class _ListStub:
        def __init__(self) -> None:
            self.calls = 0

        async def list_installation_repositories(
            self, **kwargs: Any
        ) -> tuple[list[dict[str, Any]], bool]:
            self.calls += 1
            return sentinel_rows, True

    inst = GitHubInstallation(
        installation_id=1,
        account_login="octo",
        account_type="User",
        repository_selection="selected",
        user_id=uuid4(),
    )
    stub = _ListStub()
    repos, truncated = await list_repos_for_installation(inst, client=stub)  # type: ignore[arg-type]
    assert stub.calls == 1
    assert repos == sentinel_rows
    assert truncated is True

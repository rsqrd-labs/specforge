"""Tests for the PR-with-tests export mode (Phase 21 — T-276).

Three layers:

  - **Builder (pure):** stack detection across a full-stack workspace, the
    scaffold map (CI workflow + per-task red stubs tagged with ``task_ref``),
    and the ``Closes #N`` PR body.
  - **Client (httpx.MockTransport):** the ``Workflows: write`` 403 surfaces a
    distinct typed error, and a content-write 409 refetches the SHA *on the
    write branch* and retries.
  - **Orchestration (real DB + stub client):** a finalised workspace opens one
    branch + one PR linking ``Closes #N``; a resumed export reuses the same
    branch and PR (never duplicates).
"""

from __future__ import annotations

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
    Stage,
    StageVersion,
    User,
    Workspace,
)
from services.integrations import pr_export_builder
from services.integrations.github_api_client import (
    GitHubWorkflowsPermissionError,
    make_app_github_client,
)
from services.integrations.task_parser import compute_task_ref, parse_tasks
from services.pipeline.github_export_service import (
    prepare_export_push,
    run_export_push,
)

_HARNESS_FULLSTACK = """\
## File: harness/tests/test_api.py

```python
def test_api() -> None:
    assert True
```

## File: harness/tests/ui.test.ts

```ts
import { it, expect } from "vitest"
it("ui", () => { expect(true).toBe(true) })
```
"""

_TASKS_CONTENT = """\
### T-001: First task

**Description:** Do thing one.

### T-002: Second task

**Description:** Do thing two.
"""


# ===========================================================================
# Builder — pure, no I/O
# ===========================================================================


def test_detect_stacks_full_stack_returns_both() -> None:
    harness = parse_harness_files_map()
    stacks = pr_export_builder.detect_stacks("# plan", harness)
    assert pr_export_builder.STACK_PYTHON in stacks
    assert pr_export_builder.STACK_NODE in stacks


def parse_harness_files_map() -> dict[str, str]:
    from services.pipeline.export_service import parse_harness_files

    return parse_harness_files(_HARNESS_FULLSTACK)


def test_detect_stacks_falls_back_to_plan_when_no_harness_extensions() -> None:
    stacks = pr_export_builder.detect_stacks(
        "We will use FastAPI and pytest.", {"harness/README.md": "x"}
    )
    assert stacks == [pr_export_builder.STACK_PYTHON]


def test_detect_stacks_defaults_to_python_when_ambiguous() -> None:
    assert pr_export_builder.detect_stacks("", {}) == [pr_export_builder.STACK_PYTHON]


def test_build_scaffold_emits_ci_workflow_and_per_task_stubs() -> None:
    harness = parse_harness_files_map()
    tasks = parse_tasks(_TASKS_CONTENT)
    stacks = pr_export_builder.detect_stacks("", harness)
    scaffold = pr_export_builder.build_scaffold(
        harness_files=harness, tasks=tasks, stacks=stacks
    )

    # CI workflow present with a job per detected stack.
    assert pr_export_builder.CI_WORKFLOW_PATH in scaffold
    workflow = scaffold[pr_export_builder.CI_WORKFLOW_PATH]
    assert "pytest" in workflow and "vitest" in workflow

    # One stub per task per stack, tagged with the stable task_ref.
    ref_001 = compute_task_ref("First task")
    py_stub = f"tests/specforge/test_{ref_001.replace('-', '_')}.py"
    ts_stub = f"tests/specforge/{ref_001}.test.ts"
    assert py_stub in scaffold and ts_stub in scaffold
    assert ref_001 in scaffold[py_stub]
    # The stub is RED on purpose.
    assert "AssertionError" in scaffold[py_stub]
    assert "expect(false).toBe(true)" in scaffold[ts_stub]
    # The harness contract files are carried onto the branch too.
    assert "harness/tests/test_api.py" in scaffold


def test_build_pr_body_links_closes_n() -> None:
    tasks = parse_tasks(_TASKS_CONTENT)
    # issue_numbers is keyed on the stable compute_task_ref(title) (audit #2).
    body = pr_export_builder.build_pr_body(
        tasks=tasks,
        issue_numbers={
            compute_task_ref("First task"): 11,
            compute_task_ref("Second task"): 12,
        },
        stacks=["python"],
    )
    assert "Closes #11" in body
    assert "Closes #12" in body
    # The human T-NNN remains in the display text of the link.
    assert "T-001: First task" in body


def test_stub_neutralises_untrusted_title() -> None:
    # A workspace-controlled title must not break out of the generated string
    # literal — double quotes are folded to single quotes before interpolation.
    tasks = parse_tasks('### T-001: Evil " title\n\nx\n')
    scaffold = pr_export_builder.build_scaffold(
        harness_files={}, tasks=tasks, stacks=["python"]
    )
    ref = compute_task_ref('Evil " title')
    stub = scaffold[f"tests/specforge/test_{ref.replace('-', '_')}.py"]
    assert "Evil ' title" in stub
    assert 'Evil " title' not in stub


# ===========================================================================
# Client — httpx.MockTransport
# ===========================================================================


class _FakeTokenSource:
    async def get(self, installation_id: int) -> str:
        return "tok"

    async def refresh(self, installation_id: int) -> str:
        return "tok"


def _client(handler) -> Any:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return make_app_github_client(_FakeTokenSource(), 1, http), http


@pytest.mark.asyncio
async def test_pr_mode_workflows_write_403_surfaces_clear_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # A 403 specifically on a .github/workflows/* PUT.
        return httpx.Response(
            403,
            json={"message": "refusing to allow an App to create or update workflow"},
        )

    client, http = _client(handler)
    with pytest.raises(GitHubWorkflowsPermissionError) as caught:
        await client.upsert_file(
            "o/r",
            ".github/workflows/specforge.yml",
            "name: x",
            None,
            "ci",
            branch="specforge/inc-1",
        )
    assert "Workflows: write" in str(caught.value)
    await http.aclose()


@pytest.mark.asyncio
async def test_workflows_403_not_preempted_by_governor() -> None:
    """Production wires a governor into the client. A plain permission 403 has no
    rate-limit headers/body, so the governor must NOT reclassify it as a throttle
    — the Workflows:write error must still surface."""
    from services.integrations.github_api_client import make_app_github_client
    from services.integrations.github_governor import InstallationRateGovernor

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"message": "refusing to allow an App to update workflow"}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    governor = InstallationRateGovernor(None, installation_id=1)  # no Redis: fail-open
    client = make_app_github_client(_FakeTokenSource(), 1, http, governor=governor)
    with pytest.raises(GitHubWorkflowsPermissionError):
        await client.upsert_file(
            "o/r", ".github/workflows/specforge.yml", "x", None, "ci", branch="b"
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_pr_mode_content_409_refetches_sha_and_retries() -> None:
    seen: list[tuple[str, str]] = []  # (method, url)
    state = {"puts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.method == "GET":
            # Refetch returns the *current* blob SHA on the write branch.
            return httpx.Response(200, json={"sha": "fresh-sha"})
        # First PUT 409s on the stale SHA; the retry (with the refetched SHA) wins.
        state["puts"] += 1
        if state["puts"] == 1:
            return httpx.Response(409, json={"message": "is at ... but expected ..."})
        return httpx.Response(200, json={})

    client, http = _client(handler)
    await client.upsert_file(
        "o/r", "src/app.py", "print(1)", "stale-sha", "msg", branch="specforge/inc-1"
    )

    # Exactly one refetch GET happened, and it carried ?ref=<branch>.
    gets = [url for (m, url) in seen if m == "GET"]
    assert len(gets) == 1
    assert "ref=specforge%2Finc-1" in gets[0] or "ref=specforge/inc-1" in gets[0]
    assert state["puts"] == 2  # stale → retry → success
    await http.aclose()


@pytest.mark.asyncio
async def test_get_ref_and_create_branch_and_pr_plumbing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "GET" and "/git/ref/" in url:
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if request.method == "POST" and url.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if request.method == "POST" and url.endswith("/pulls"):
            return httpx.Response(201, json={"number": 42})
        return httpx.Response(500, json={"message": "unexpected"})

    client, http = _client(handler)
    sha = await client.get_ref("o/r", "heads/main")
    assert sha == "base-sha"
    await client.create_branch("o/r", "specforge/inc-1", sha)
    number = await client.create_pull_request(
        "o/r", head="specforge/inc-1", base="main", title="t", body="b"
    )
    assert number == 42
    await http.aclose()


@pytest.mark.asyncio
async def test_create_pull_request_recovers_existing_pr_on_422() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.endswith("/pulls"):
            return httpx.Response(
                422, json={"message": "A pull request already exists"}
            )
        if request.method == "GET" and "/pulls?" in url:
            return httpx.Response(
                200, json=[{"number": 7, "head": {"ref": "specforge/inc-1"}}]
            )
        return httpx.Response(500, json={"message": "unexpected"})

    client, http = _client(handler)
    number = await client.create_pull_request(
        "o/r", head="specforge/inc-1", base="main", title="t", body="b"
    )
    assert number == 7  # recovered, not duplicated
    await http.aclose()


@pytest.mark.asyncio
async def test_create_branch_is_idempotent_on_422_already_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Reference already exists"})

    client, http = _client(handler)
    # Must not raise — a resumed export reuses the same branch.
    await client.create_branch("o/r", "specforge/inc-1", "base-sha")
    await http.aclose()


# ===========================================================================
# Orchestration — real DB + stub client
# ===========================================================================


class _PRStubClient:
    """Records branch/PR plumbing so the PR-mode flow is observable."""

    def __init__(self) -> None:
        self.created_repos: list[tuple[str, bool]] = []
        self.upserts: list[tuple[str, str | None]] = []  # (path, branch)
        self.branches: list[tuple[str, str]] = []  # (branch, base_sha)
        self.pulls_created: list[tuple[str, str]] = []  # (head, base)
        self.issues_created: list[str] = []
        self.issues_updated: list[int] = []
        self._issue_counter = 100
        self._pr_counter = 0
        self.shas: dict[str, str] = {}

    async def get_repo(self, owner_repo: str) -> dict[str, Any] | None:
        return None  # repo doesn't exist yet, by default

    async def create_org_repo(
        self, org: str, name: str, private: bool
    ) -> dict[str, Any]:
        self.created_repos.append((name, private))
        return {
            "full_name": f"{org}/{name}",
            "html_url": f"https://github.com/{org}/{name}",
            "id": 999,
        }

    async def get_file_sha(
        self, repo: str, path: str, *, ref: str | None = None
    ) -> str | None:
        return self.shas.get((path, ref) if ref else path)  # type: ignore[arg-type]

    async def get_file_content(
        self, repo: str, path: str, *, ref: str | None = None
    ) -> tuple[str, str] | None:
        return None  # AGENTS.md does not exist yet in these tests

    async def upsert_file(
        self, repo, path, content, sha, commit_message, *, branch=None
    ) -> None:
        self.upserts.append((path, branch))

    async def create_issue(
        self, repo: str, title: str, body: str, *, labels=None
    ) -> int:
        self.issues_created.append(title)
        self._issue_counter += 1
        return self._issue_counter

    async def update_issue(self, repo, number, title, body, *, labels=None) -> None:
        self.issues_updated.append(number)

    async def get_ref(self, repo: str, ref: str) -> str:
        return "base-sha"

    async def create_branch(self, repo: str, branch: str, base_sha: str) -> None:
        self.branches.append((branch, base_sha))

    async def create_pull_request(self, repo, *, head, base, title, body) -> int:
        self.pulls_created.append((head, base))
        self._pr_counter += 1
        return 4200 + self._pr_counter


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
        email=f"pr-{uuid4()}@example.com",
        google_id=f"g-{uuid4()}",
        name="T",
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
        name="PR WS",
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
        ("plan", "# plan with pytest and vitest"),
        ("harness", _HARNESS_FULLSTACK),
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
        session.add(
            StageVersion(
                stage_id=stage.id, version=1, content=content, created_by="user"
            )
        )
    await session.commit()
    yield ws
    await session.execute(delete(Workspace).where(Workspace.id == ws.id))
    await session.commit()


@pytest.fixture
async def installation(session: AsyncSession, user: User) -> GitHubInstallation:
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
    await session.execute(
        delete(IntegrationPush).where(IntegrationPush.installation_id == inst.id)
    )
    await session.execute(
        delete(GitHubInstallation).where(GitHubInstallation.id == inst.id)
    )
    await session.commit()


@pytest.mark.asyncio
async def test_pr_mode_opens_branch_and_pr_and_links_closes_n(
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
        export_mode="pr_with_tests",
    )
    stub = _PRStubClient()
    result = await run_export_push(push.id, "proj", "private", db=session, client=stub)

    assert result is not None and result.status == "completed"
    # One branch, one PR.
    assert stub.branches == [("specforge/inc-1", "base-sha")]
    assert stub.pulls_created == [("specforge/inc-1", "main")]
    assert result.branch_name == "specforge/inc-1"
    assert result.pr_number == 4201

    # Docs went to the default branch (branch=None); scaffold went to the branch.
    docs_on_default = {p for (p, b) in stub.upserts if b is None}
    on_branch = {p for (p, b) in stub.upserts if b == "specforge/inc-1"}
    assert {"SPEC.md", "PLAN.md", "TASKS.md"} <= docs_on_default
    assert pr_export_builder.CI_WORKFLOW_PATH in on_branch
    assert any(p.startswith("tests/specforge/") for p in on_branch)
    # Harness contracts are NOT on the default branch (disjoint set).
    assert not any(p.startswith("harness/") for p in docs_on_default)
    # Two issues created for the PR's Closes #N links.
    assert len(stub.issues_created) == 2


@pytest.mark.asyncio
async def test_pr_mode_reexport_reuses_branch_and_pr(
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
        export_mode="pr_with_tests",
    )
    first = _PRStubClient()
    await run_export_push(push.id, "proj", "private", db=session, client=first)
    assert first.pulls_created == [("specforge/inc-1", "main")]

    # Simulate a re-export (at-least-once / resync): reset to pending and re-run.
    push.status = "pending"
    await session.commit()

    second = _PRStubClient()
    result = await run_export_push(
        push.id, "proj", "private", db=session, client=second
    )

    assert result is not None and result.status == "completed"
    assert second.created_repos == []  # repo reused
    assert second.pulls_created == []  # PR NOT duplicated (pr_number persisted)
    assert second.issues_created == []  # issues updated, not recreated
    assert len(second.issues_updated) == 2
    assert result.pr_number == 4201  # same PR number as the first export

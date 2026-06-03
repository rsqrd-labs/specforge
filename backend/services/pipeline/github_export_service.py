"""GitHub export orchestrator.

Drives the full export sequence: validates the user's GitHub connection,
creates or reuses a repo, pushes all four stage files (same layout as the
ZIP export), and creates one GitHub Issue per T-NNN task.

State machine:

    [no push row]                   [push row exists]
            \\                          /
             v                        v
        status="in_progress" (push row is the lock — commit before any GitHub call)
                       |
        if repo_full_name is None: create_repo
                       |
              push files (idempotent: get_file_sha → upsert_file)
                       |
              create/update issues sequentially
                       |
        status="success" + pushed_at + integration.last_used_at

On ``GitHubTokenExpiredError``:
  1. Delete UserIntegration in its own commit (a single-transaction wrap
     would lose the invalidation if the push update fails for any reason).
  2. Mark push as ``status="error"``.
  3. Re-raise.

On any other exception after the push row is committed:
  - Mark push as ``status="error"`` and re-raise. Re-export resumes from
    the same row — partial state (files pushed, issues partially created)
    is preserved because the IntegrationPushTask rows are committed one
    per issue.

Idempotent re-export:
  - Existing IntegrationPush row is reused — never creates a duplicate repo.
  - Files: ``get_file_sha`` returns the existing blob SHA; ``upsert_file``
    sends a PUT with the SHA which GitHub treats as an update.
  - Issues: existing IntegrationPushTask rows map T-NNN refs to issue
    numbers; we ``update_issue`` for those and ``create_issue`` for any
    new tasks added since the last export.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_shared_redis
from models import (
    GitHubInstallation,
    IntegrationPush,
    IntegrationPushTask,
    Stage,
    StageVersion,
    UserIntegration,
    Workspace,
)
from services.integrations import agents_md_builder, pr_export_builder
from services.integrations.github_api_client import (
    GitHubAPIClient,
    GitHubAPIError,
    GitHubNotConnectedError,
    GitHubRateLimitError,
    GitHubRepoExistsError,
    GitHubTokenExpiredError,
    GitHubUnavailableError,
    make_app_github_client,
    make_github_client,
    make_shared_async_client,
)
from services.integrations.github_app_auth import make_token_provider
from services.integrations.github_governor import (
    GitHubThrottledError,
    InstallationRateGovernor,
    make_governor,
)
from services.integrations.task_parser import ParsedTask, parse_tasks
from services.pipeline.export_service import ExportNotReadyError, parse_harness_files
from services.security import key_vault

logger = logging.getLogger(__name__)

GITHUB_PROVIDER = "github"
_STAGE_FILES = {"spec": "SPEC.md", "plan": "PLAN.md", "tasks": "TASKS.md"}
_HTTP_TIMEOUT_SECONDS = 30.0

# PR-mode (T-276) constants. A new repo is created with no commits, so its
# default branch only exists after the first push; ``create_repo`` makes a
# repo whose default branch is ``main``. The increment branch name is
# deterministic so a resumed export reuses the same branch (create → 422 no-op)
# instead of opening a second PR.
_DEFAULT_BRANCH = "main"
_INCREMENT_BRANCH = "specforge/inc-1"

# Type alias for a GitHubAPIClient factory. Tests inject a stub here so they
# do not need to construct an httpx.AsyncClient.
ClientFactory = type[GitHubAPIClient]


async def push_to_github(
    workspace_id: UUID,
    user_id: UUID,
    repo_name: str,
    visibility: str,
    db: AsyncSession,
    *,
    client_factory: object = None,
) -> IntegrationPush:
    """Push a workspace to a GitHub repo, creating issues per task.

    Parameters mirror the T-153 router signature. ``client_factory`` is an
    optional override used by tests to inject a stub GitHub client — the
    production code path passes ``None`` and a real httpx client is built.

    Returns the IntegrationPush row in ``status="success"`` on completion.
    Raises:
        GitHubNotConnectedError: user has no GitHub integration row.
        ExportNotReadyError: workspace or any stage not finalised.
        GitHubRepoExistsError: first-time export and the repo name is taken.
        GitHubTokenExpiredError: any 401 from GitHub. The UserIntegration
            row is deleted before re-raising.
        GitHubRateLimitError: any 429 or rate-limited 403.
        GitHubAPIError: any other non-2xx GitHub response.
    """
    # 1. Pre-flight validation (do this before creating the push row so a
    #    failed precondition does not leave orphan "in_progress" rows).
    workspace = await _load_workspace(db, workspace_id, user_id)
    stages = await _load_finalised_stages(db, workspace_id)

    integration = await _load_integration(db, user_id)
    if integration is None:
        raise GitHubNotConnectedError("GitHub integration not connected for this user")

    plaintext_token = key_vault.decrypt(integration.encrypted_token)

    # 2. Upsert the push row — this is the durable lock against duplicate
    #    repo creation. Commit before any GitHub call.
    push = await _upsert_push_row(db, workspace_id, user_id)

    # 3. Drive the actual export with a typed-exception boundary.
    if client_factory is None:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as http:
            client = make_github_client(plaintext_token, http)
            try:
                return await _run_export(
                    db=db,
                    workspace=workspace,
                    stages=stages,
                    integration=integration,
                    push=push,
                    client=client,
                    repo_name=repo_name,
                    visibility=visibility,
                )
            except GitHubTokenExpiredError:
                await _handle_token_expired(db, user_id, push)
                raise
            except (
                GitHubRepoExistsError,
                GitHubRateLimitError,
                GitHubAPIError,
                ExportNotReadyError,
                Exception,
            ):
                await _mark_push_failed(db, push)
                raise
    else:
        # Test path: caller provides a ready-made GitHubAPIClient.
        client = client_factory  # type: ignore[assignment]
        try:
            return await _run_export(
                db=db,
                workspace=workspace,
                stages=stages,
                integration=integration,
                push=push,
                client=client,
                repo_name=repo_name,
                visibility=visibility,
            )
        except GitHubTokenExpiredError:
            await _handle_token_expired(db, user_id, push)
            raise
        except (
            GitHubRepoExistsError,
            GitHubRateLimitError,
            GitHubAPIError,
            ExportNotReadyError,
            Exception,
        ):
            await _mark_push_failed(db, push)
            raise


# ---------------------------------------------------------------------------
# Public lookup
# ---------------------------------------------------------------------------


async def get_push(
    workspace_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> IntegrationPush | None:
    """Return the GitHub push record for the workspace, with issue_count populated.

    Returns ``None`` if no push has ever been initiated. Caller is expected
    to translate ``None`` to a 404 at the HTTP layer.
    """
    result = await db.execute(
        select(IntegrationPush).where(
            IntegrationPush.workspace_id == workspace_id,
            IntegrationPush.user_id == user_id,
            IntegrationPush.provider == GITHUB_PROVIDER,
        )
    )
    push = result.scalar_one_or_none()
    if push is None:
        return None
    push.issue_count = await _count_issues(db, push.id)  # type: ignore[attr-defined]
    return push


# ---------------------------------------------------------------------------
# App-mode export (Phase 21 — T-269): request path prepares, worker executes
# ---------------------------------------------------------------------------


async def load_owned_installation(
    db: AsyncSession,
    installation_id: UUID,
    user_id: UUID,
) -> GitHubInstallation | None:
    """Return the installation iff it exists and is owned by ``user_id``.

    The owner check is the confused-deputy guard: a user may only export under an
    installation they linked, never another tenant's.
    """
    result = await db.execute(
        select(GitHubInstallation).where(GitHubInstallation.id == installation_id)
    )
    installation = result.scalar_one_or_none()
    if installation is None or installation.user_id != user_id:
        return None
    return installation


async def prepare_export_push(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    installation: GitHubInstallation,
    export_mode: str,
) -> IntegrationPush:
    """Validate and create/reset the ``pending`` push row for an App export.

    Runs on the request path before enqueuing the ``export_push`` job. Validates
    workspace ownership and that every stage is finalised (raising
    :class:`ExportNotReadyError`), then reuses the workspace's single GitHub push
    row (or creates one), binding it to the target installation and resetting it
    to ``pending`` so :func:`run_export_push` can drive it on the worker.

    The actual GitHub I/O — repo creation, file push, issue creation — happens on
    the worker, never here.
    """
    await _load_workspace(db, workspace_id, user_id)
    await _load_finalised_stages(db, workspace_id)

    result = await db.execute(
        select(IntegrationPush).where(
            IntegrationPush.workspace_id == workspace_id,
            IntegrationPush.provider == GITHUB_PROVIDER,
        )
    )
    push = result.scalar_one_or_none()
    if push is None:
        push = IntegrationPush(
            workspace_id=workspace_id,
            user_id=user_id,
            provider=GITHUB_PROVIDER,
            status="pending",
        )
        db.add(push)
    else:
        push.status = "pending"
    push.installation_id = installation.id
    push.export_mode = export_mode
    await db.commit()
    await db.refresh(push)
    return push


async def run_export_push(
    push_id: UUID,
    repo_name: str,
    visibility: str,
    *,
    db: AsyncSession,
    client: GitHubAPIClient | None = None,
) -> IntegrationPush | None:
    """Execute a prepared App-mode export (the body of the ``export_push`` job).

    Idempotent and resumable (keyed by ``push_id``): a re-run after a crash or
    rate-limit resumes from the ledger — it never re-creates a repo whose
    ``repo_full_name`` is already recorded, nor an issue already in
    ``integration_push_tasks``. A push already ``completed`` is a no-op.

    On success it persists the three fields the rest of the loop depends on —
    ``repo_id`` (from ``repository.id``), ``installation_id`` (already bound by
    :func:`prepare_export_push`), and ``source_stage_version_id`` (the Tasks
    ``StageVersion`` that produced this push) — and sets ``status='completed'``.
    Without these, token re-mint/confused-deputy (T-272), drift compare (T-273),
    and the ``find_live_push`` lookup (T-266) are all inert.

    ``client`` is injected by tests; in production an App-mode client is built
    from the bound installation's token provider.
    """
    push = await _load_push_by_id(db, push_id)
    if push is None:
        logger.warning("github_export.push_missing", extra={"push_id": str(push_id)})
        return None
    if push.status == "completed":
        return push  # already done — at-least-once safe

    installation = await _load_installation(db, push.installation_id)
    if installation is None:
        await _mark_push_failed(db, push, status="failed")
        raise GitHubNotConnectedError("GitHub App installation not found for this push")

    workspace = await _load_workspace_by_id(db, push.workspace_id)
    stages = await _load_finalised_stages(db, push.workspace_id)
    source_version_id = await _resolve_source_stage_version_id(db, stages["tasks"])

    if client is not None:
        # Injected client (tests): no governor — serialization/budget are no-ops.
        return await _drive_app_export(
            db=db,
            workspace=workspace,
            stages=stages,
            push=push,
            client=client,
            governor=None,
            repo_name=repo_name,
            visibility=visibility,
            source_version_id=source_version_id,
        )

    async with make_shared_async_client() as http:
        redis = get_shared_redis()
        token_provider = make_token_provider(redis, http)
        # Per-installation governor (T-274): budgets every call against GitHub's
        # primary/secondary limits and serializes this repo's content writes.
        governor = make_governor(installation.installation_id, redis)
        built = make_app_github_client(
            token_provider,
            installation.installation_id,
            http,
            governor=governor,
        )
        return await _drive_app_export(
            db=db,
            workspace=workspace,
            stages=stages,
            push=push,
            client=built,
            governor=governor,
            repo_name=repo_name,
            visibility=visibility,
            source_version_id=source_version_id,
        )


async def _drive_app_export(
    *,
    db: AsyncSession,
    workspace: Workspace,
    stages: dict[str, Stage],
    push: IntegrationPush,
    client: GitHubAPIClient,
    governor: InstallationRateGovernor | None,
    repo_name: str,
    visibility: str,
    source_version_id: UUID | None,
) -> IntegrationPush:
    try:
        return await _run_app_export(
            db=db,
            workspace=workspace,
            stages=stages,
            push=push,
            client=client,
            governor=governor,
            repo_name=repo_name,
            visibility=visibility,
            source_version_id=source_version_id,
        )
    except (GitHubThrottledError, GitHubUnavailableError):
        # Backpressure (T-274) and a tripped circuit breaker are NOT failures:
        # the push stays live (non-'failed', so find_live_push still sees it) and
        # the worker requeues — throttle defers off the try budget, breaker-open
        # surfaces "sync paused" and retries. Marking 'failed' here would wrongly
        # drop the live push and skip the resume.
        raise
    except Exception:
        # A genuine failure marks the push failed and re-raises so the worker base
        # contract can retry/backoff and ultimately dead-letter. v2 status is
        # 'failed' so find_live_push (status <> 'failed') excludes it.
        await _mark_push_failed(db, push, status="failed")
        raise


async def _run_app_export(
    *,
    db: AsyncSession,
    workspace: Workspace,
    stages: dict[str, Stage],
    push: IntegrationPush,
    client: GitHubAPIClient,
    governor: InstallationRateGovernor | None,
    repo_name: str,
    visibility: str,
    source_version_id: UUID | None,
) -> IntegrationPush:
    # Step 1 — create repo (first run only). Resume skips this when the repo is
    # already recorded, so a re-run never creates a second repo. A brand-new repo
    # has no concurrent writer yet, so this single create runs outside the
    # per-repo lock (which keys on repo_id, only known after this step).
    if push.repo_full_name is None:
        repo_data = await client.create_repo(
            repo_name, private=(visibility == "private")
        )
        full_name = repo_data.get("full_name")
        repo_id = repo_data.get("id")
        html_url = repo_data.get("html_url")
        if not isinstance(full_name, str):
            raise GitHubAPIError(0, "create_repo response missing full_name")
        push.repo_full_name = full_name
        push.repo_url = html_url if isinstance(html_url, str) else None
        # repo_id is the immutable reconciliation key (T-266/T-272/T-273).
        if isinstance(repo_id, int):
            push.repo_id = repo_id
        await db.commit()
        await db.refresh(push)

    assert push.repo_full_name is not None  # nosec B101 — set by the branch above

    # Steps 2–3 — all content writes to this repo are serialized under a
    # per-repo_id lock (T-274) so two concurrent jobs cannot race on the blob SHA
    # (stale-SHA 409) or trip GitHub's secondary abuse-detection on one repo. PR
    # mode dispatches *inside* this wrapped + locked path so it inherits the
    # T-274 throttle/breaker handling and the serialization for free.
    lock = (
        governor.repo_write_lock(push.repo_id)
        if governor is not None
        else nullcontext()
    )
    tasks = parse_tasks(stages["tasks"].content or "")
    async with lock:
        if push.export_mode == "pr_with_tests":
            await _write_pr_with_tests(
                db=db,
                client=client,
                push=push,
                workspace=workspace,
                stages=stages,
                tasks=tasks,
            )
        else:
            await _write_files_to_default(
                db=db,
                client=client,
                push=push,
                workspace=workspace,
                stages=stages,
                tasks=tasks,
            )

    # Step 4 — finalise. Persist the three loop-critical fields and complete.
    push.source_stage_version_id = source_version_id
    push.status = "completed"
    push.pushed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(push)
    push.issue_count = await _count_issues(db, push.id)  # type: ignore[attr-defined]
    return push


async def _write_files_to_default(
    *,
    db: AsyncSession,
    client: GitHubAPIClient,
    push: IntegrationPush,
    workspace: Workspace,
    stages: dict[str, Stage],
    tasks: list[ParsedTask],
) -> None:
    """Phase-13 export: push every file to the default branch, create issues."""
    assert push.repo_full_name is not None  # nosec B101
    repo = push.repo_full_name
    files_to_push = _build_file_map(stages)
    commit_message = f"chore: SpecForge export — {workspace.name}"
    for path, content in files_to_push.items():
        sha = await client.get_file_sha(repo, path)
        await client.upsert_file(repo, path, content, sha, commit_message)
    await _push_agents_md(client, repo, stages)
    await _sync_issues(db, client, repo, push, tasks)


async def _write_pr_with_tests(
    *,
    db: AsyncSession,
    client: GitHubAPIClient,
    push: IntegrationPush,
    workspace: Workspace,
    stages: dict[str, Stage],
    tasks: list[ParsedTask],
) -> None:
    """Open the Harness stage as an executable pull request (T-276).

    Docs (SPEC/PLAN/TASKS) land on the default branch as the base; the harness
    contracts, the CI workflow, and one red stub per task land on a deterministic
    increment branch; a single PR links the issues via ``Closes #N``. Every step
    is idempotent so a resumed export updates in place and never duplicates the
    branch or the PR.
    """
    assert push.repo_full_name is not None  # nosec B101
    repo = push.repo_full_name

    # 1. Docs → default branch (establishes `main` on a fresh, empty repo).
    docs = {
        filename: stages[stage_type].content or ""
        for stage_type, filename in _STAGE_FILES.items()
    }
    docs_message = f"docs: SpecForge spec — {workspace.name}"
    for path, content in docs.items():
        sha = await client.get_file_sha(repo, path)
        await client.upsert_file(repo, path, content, sha, docs_message)
    # Repo-level agent context on the default branch alongside the docs.
    await _push_agents_md(client, repo, stages)

    # 2. Issues (records issue numbers used for the PR's Closes #N links).
    issue_numbers = await _sync_issues(db, client, repo, push, tasks)

    # 3. Branch off the default branch base. Deterministic name + 422-tolerant
    #    create → a resumed export reuses the same branch instead of failing.
    if push.branch_name is None:
        push.branch_name = _INCREMENT_BRANCH
    base_sha = await client.get_ref(repo, f"heads/{_DEFAULT_BRANCH}")
    await client.create_branch(repo, push.branch_name, base_sha)
    await db.commit()

    # 4. Harness contracts + CI workflow + per-task red stubs → the branch.
    harness_files = parse_harness_files(stages["harness"].content or "")
    stacks = pr_export_builder.detect_stacks(
        stages["plan"].content or "", harness_files
    )
    scaffold = pr_export_builder.build_scaffold(
        harness_files=harness_files, tasks=tasks, stacks=stacks
    )
    scaffold_message = f"test: SpecForge harness — {workspace.name}"
    for path, content in scaffold.items():
        sha = await client.get_file_sha(repo, path, ref=push.branch_name)
        await client.upsert_file(
            repo, path, content, sha, scaffold_message, branch=push.branch_name
        )

    # 5. One PR, reused on re-export (persisted pr_number → never duplicated).
    if push.pr_number is None:
        body = pr_export_builder.build_pr_body(
            tasks=tasks, issue_numbers=issue_numbers, stacks=stacks
        )
        title = f"SpecForge harness — {workspace.name}"
        push.pr_number = await client.create_pull_request(
            repo, head=push.branch_name, base=_DEFAULT_BRANCH, title=title, body=body
        )
        await db.commit()


async def _sync_issues(
    db: AsyncSession,
    client: GitHubAPIClient,
    repo: str,
    push: IntegrationPush,
    tasks: list[ParsedTask],
) -> dict[str, int]:
    """Create/update one issue per task; return the ``{task_ref: issue#}`` map.

    Each new issue is committed immediately so a mid-run rate-limit resumes
    without recreating issues 1..N-1.
    """
    existing = await _load_existing_push_tasks(db, push.id)
    issue_numbers: dict[str, int] = dict(existing)
    for parsed in tasks:
        existing_number = existing.get(parsed.ref)
        # Agent-ready body + labels (T-277): the issue is an optimal agent prompt.
        if existing_number is not None:
            await client.update_issue(
                repo,
                existing_number,
                parsed.title,
                parsed.agent_body_md,
                labels=parsed.labels,
            )
        else:
            number = await client.create_issue(
                repo, parsed.title, parsed.agent_body_md, labels=parsed.labels
            )
            db.add(
                IntegrationPushTask(
                    push_id=push.id,
                    task_ref=parsed.ref,
                    external_issue_number=number,
                )
            )
            await db.commit()
            issue_numbers[parsed.ref] = number
    return issue_numbers


async def _push_agents_md(
    client: GitHubAPIClient,
    repo: str,
    stages: dict[str, Stage],
    *,
    branch: str | None = None,
) -> None:
    """Write a non-clobbering ``AGENTS.md`` to the repo (T-277).

    Reads any existing file first so a hand-written ``AGENTS.md`` is preserved —
    only SpecForge's delimited managed block is (re)generated. Deterministic
    output means a re-sync with unchanged stages produces an identical file (no
    spurious commit).
    """
    stage_md = {stage_type: (stages[stage_type].content or "") for stage_type in stages}
    existing = await client.get_file_content(repo, "AGENTS.md", ref=branch)
    existing_text = existing[0] if existing else None
    existing_sha = existing[1] if existing else None
    content = agents_md_builder.build_agents_md(stage_md, existing=existing_text)
    if existing is not None and content == existing_text:
        return  # idempotent — nothing changed, skip the write (no empty commit)
    await client.upsert_file(
        repo,
        "AGENTS.md",
        content,
        existing_sha,
        "docs: SpecForge agent context",
        branch=branch,
    )


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------


async def _run_export(
    *,
    db: AsyncSession,
    workspace: Workspace,
    stages: dict[str, Stage],
    integration: UserIntegration,
    push: IntegrationPush,
    client: GitHubAPIClient,
    repo_name: str,
    visibility: str,
) -> IntegrationPush:
    # Step 4 — create repo (first export only)
    if push.repo_full_name is None:
        repo_data = await client.create_repo(
            repo_name, private=(visibility == "private")
        )
        full_name = repo_data.get("full_name")
        html_url = repo_data.get("html_url")
        if not isinstance(full_name, str):
            raise GitHubAPIError(0, "create_repo response missing full_name")
        push.repo_full_name = full_name
        push.repo_url = html_url if isinstance(html_url, str) else None
        await db.commit()
        await db.refresh(push)

    assert push.repo_full_name is not None  # nosec — guaranteed by branch above

    # Step 5 — push files
    files_to_push = _build_file_map(stages)
    commit_message = f"chore: SpecForge export — {workspace.name}"
    for path, content in files_to_push.items():
        sha = await client.get_file_sha(push.repo_full_name, path)
        await client.upsert_file(
            push.repo_full_name,
            path,
            content,
            sha,
            commit_message,
        )

    # Step 6 — create/update issues sequentially. GitHub has a secondary
    # rate limit on content creation; gathering these would trip it.
    existing_tasks = await _load_existing_push_tasks(db, push.id)
    tasks = parse_tasks(stages["tasks"].content or "")
    for parsed in tasks:
        existing_number = existing_tasks.get(parsed.ref)
        if existing_number is not None:
            await client.update_issue(
                push.repo_full_name,
                existing_number,
                parsed.title,
                parsed.body_md,
            )
        else:
            number = await client.create_issue(
                push.repo_full_name,
                parsed.title,
                parsed.body_md,
            )
            db.add(
                IntegrationPushTask(
                    push_id=push.id,
                    task_ref=parsed.ref,
                    external_issue_number=number,
                )
            )
            # Commit each new issue so partial failure (e.g. rate limit on
            # issue #50 of 100) preserves issues 1-49 — re-export resumes
            # from #50 without recreating them.
            await db.commit()

    # Step 7 — finalise
    push.status = "success"
    push.pushed_at = datetime.now(UTC)
    integration.last_used_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(push)

    push.issue_count = await _count_issues(db, push.id)  # type: ignore[attr-defined]
    return push


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def _handle_token_expired(
    db: AsyncSession,
    user_id: UUID,
    push: IntegrationPush,
) -> None:
    """Delete the invalidated UserIntegration row and mark the push as error.

    The two updates run as separate commits so a failure in the second
    cannot leave a known-invalid token in place. SpecForge never retries
    with a known-bad token; the user is prompted to reconnect.
    """
    try:
        await db.execute(
            delete(UserIntegration).where(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == GITHUB_PROVIDER,
            )
        )
        await db.commit()
    except Exception:
        logger.exception("github_export.token_expiry_delete_failed")
        # Continue to mark the push as failed — the integration row may
        # be gone or may not be, but we still want a status on the push.
        try:
            await db.rollback()
        except Exception:  # pragma: no cover — best-effort
            pass

    await _mark_push_failed(db, push)


async def mark_push_unstarted(db: AsyncSession, push: IntegrationPush) -> None:
    """Mark a just-prepared push ``failed`` when enqueue could not start it.

    Leaves no dangling non-``failed`` row that ``find_live_push`` would treat as
    a live push for the repo.
    """
    await _mark_push_failed(db, push, status="failed")


async def _mark_push_failed(
    db: AsyncSession, push: IntegrationPush, *, status: str = "error"
) -> None:
    try:
        push.status = status
        await db.commit()
    except Exception:
        logger.exception("github_export.mark_failed_commit_error")
        try:
            await db.rollback()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_workspace(
    db: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
) -> Workspace:
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None or workspace.user_id != user_id:
        # 404-style: never leak existence of someone else's workspace.
        raise ExportNotReadyError("Workspace not found")
    return workspace


async def _load_finalised_stages(
    db: AsyncSession,
    workspace_id: UUID,
) -> dict[str, Stage]:
    result = await db.execute(select(Stage).where(Stage.workspace_id == workspace_id))
    stages = {s.type: s for s in result.scalars()}
    for stage_type in ("spec", "plan", "harness", "tasks"):
        stage = stages.get(stage_type)
        if stage is None or stage.status != "finalised":
            raise ExportNotReadyError(
                f"Stage {stage_type!r} is not finalised — export unavailable"
            )
    return stages


async def _load_integration(
    db: AsyncSession,
    user_id: UUID,
) -> UserIntegration | None:
    result = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider == GITHUB_PROVIDER,
        )
    )
    return result.scalar_one_or_none()


async def _upsert_push_row(
    db: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
) -> IntegrationPush:
    """Reuse the workspace's existing github push or create one, marking it
    ``in_progress``.

    Historically this was a single ``INSERT ... ON CONFLICT`` on the
    ``uq_integration_push_workspace_provider`` constraint. Phase 21's migration
    ``0016`` rekeys the table onto the immutable ``repo_id`` and drops that
    constraint (a live push is now one per ``(workspace_id, repo_id)``). Legacy
    v1-OAuth pushes carry no ``repo_id`` (the partial index treats their NULL
    keys as distinct), so the legacy path keeps its "one push per workspace"
    semantics at the application level: look the row up by
    ``(workspace_id, provider)`` and reset its status, otherwise insert. Repo
    fields (``repo_full_name`` / ``repo_url``) are left untouched on re-export.
    """
    result = await db.execute(
        select(IntegrationPush).where(
            IntegrationPush.workspace_id == workspace_id,
            IntegrationPush.provider == GITHUB_PROVIDER,
        )
    )
    push = result.scalar_one_or_none()
    if push is None:
        push = IntegrationPush(
            workspace_id=workspace_id,
            user_id=user_id,
            provider=GITHUB_PROVIDER,
            status="in_progress",
        )
        db.add(push)
    else:
        push.status = "in_progress"
    await db.commit()
    await db.refresh(push)
    return push


async def _load_push_by_id(
    db: AsyncSession,
    push_id: UUID,
) -> IntegrationPush | None:
    result = await db.execute(
        select(IntegrationPush).where(IntegrationPush.id == push_id)
    )
    return result.scalar_one_or_none()


async def _load_workspace_by_id(db: AsyncSession, workspace_id: UUID) -> Workspace:
    """Load a workspace by id (worker context — ownership already enforced when
    the export was enqueued)."""
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise ExportNotReadyError("Workspace not found")
    return workspace


async def _load_installation(
    db: AsyncSession,
    installation_id: UUID | None,
) -> GitHubInstallation | None:
    if installation_id is None:
        return None
    result = await db.execute(
        select(GitHubInstallation).where(GitHubInstallation.id == installation_id)
    )
    return result.scalar_one_or_none()


async def _resolve_source_stage_version_id(
    db: AsyncSession,
    tasks_stage: Stage,
) -> UUID | None:
    """Return the StageVersion id of the Tasks stage's current version.

    Persisted on the push so drift detection (T-273) can compare the pushed
    Tasks version against the workspace's latest finalised Tasks.
    """
    result = await db.execute(
        select(StageVersion.id).where(
            StageVersion.stage_id == tasks_stage.id,
            StageVersion.version == tasks_stage.current_version,
        )
    )
    return result.scalar_one_or_none()


async def _load_existing_push_tasks(
    db: AsyncSession,
    push_id: UUID,
) -> dict[str, int]:
    """Return a map of task_ref → issue_number for the given push."""
    result = await db.execute(
        select(
            IntegrationPushTask.task_ref,
            IntegrationPushTask.external_issue_number,
        ).where(IntegrationPushTask.push_id == push_id)
    )
    return {row.task_ref: row.external_issue_number for row in result.all()}


async def _count_issues(db: AsyncSession, push_id: UUID) -> int:
    from sqlalchemy import func

    result = await db.execute(
        select(func.count())
        .select_from(IntegrationPushTask)
        .where(IntegrationPushTask.push_id == push_id)
    )
    return int(result.scalar() or 0)


def _build_file_map(stages: dict[str, Stage]) -> dict[str, str]:
    """Return the full {path: content} map of every file to push.

    SPEC.md / PLAN.md / TASKS.md at repo root, plus everything from the
    harness/ directory parsed out of stages['harness'].content via the
    same parser the ZIP export uses (single source of truth).
    """
    files: dict[str, str] = {}
    for stage_type, filename in _STAGE_FILES.items():
        files[filename] = stages[stage_type].content or ""
    harness_files = parse_harness_files(stages["harness"].content or "")
    files.update(harness_files)
    return files

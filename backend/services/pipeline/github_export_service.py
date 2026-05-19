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
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    IntegrationPush,
    IntegrationPushTask,
    Stage,
    UserIntegration,
    Workspace,
)
from services.integrations.github_api_client import (
    GitHubAPIClient,
    GitHubAPIError,
    GitHubNotConnectedError,
    GitHubRateLimitError,
    GitHubRepoExistsError,
    GitHubTokenExpiredError,
    make_github_client,
)
from services.integrations.task_parser import parse_tasks
from services.pipeline.export_service import ExportNotReadyError, parse_harness_files
from services.security import key_vault

logger = logging.getLogger(__name__)

GITHUB_PROVIDER = "github"
_STAGE_FILES = {"spec": "SPEC.md", "plan": "PLAN.md", "tasks": "TASKS.md"}
_HTTP_TIMEOUT_SECONDS = 30.0

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


async def _mark_push_failed(db: AsyncSession, push: IntegrationPush) -> None:
    try:
        push.status = "error"
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
    """Insert a new push row or set an existing one back to ``in_progress``.

    The unique constraint on (workspace_id, provider) means at most one
    row exists per provider; this upsert ensures a fresh "in_progress"
    marker without disturbing repo_full_name / repo_url on re-export.
    """
    stmt = (
        insert(IntegrationPush)
        .values(
            workspace_id=workspace_id,
            user_id=user_id,
            provider=GITHUB_PROVIDER,
            status="in_progress",
        )
        .on_conflict_do_update(
            constraint="uq_integration_push_workspace_provider",
            set_={"status": "in_progress"},
        )
        .returning(IntegrationPush)
    )
    result = await db.execute(stmt)
    push = result.scalar_one()
    await db.commit()
    await db.refresh(push)
    return push


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

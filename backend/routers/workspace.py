import logging
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db, get_redis
from middleware.auth import get_current_user
from models import Increment, IncrementIdea, IntegrationPushTask, User, Workspace
from schemas.github import (
    GitHubExportRequest,
    PushStatusResponse,
    SyncStateResponse,
    TaskSyncState,
)
from schemas.increment import (
    IdeaCreate,
    IdeaRead,
    IncrementCreate,
    IncrementGenerateResponse,
    IncrementPushResponse,
    IncrementRead,
)
from schemas.integration import (
    GitHubExportResponse,
    IntegrationPushRead,
)
from schemas.workspace import (
    ClarifyResponse,
    ClarifySubmitRequest,
    ShareLinkResponse,
    TrashedWorkspaceResponse,
    WorkspaceCreate,
    WorkspaceCriticToggle,
    WorkspaceResearchToggle,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from services.coverage_utils import derive_coverage_summaries, derive_coverage_summary
from services.credit_service import InsufficientCreditsError
from services.integrations.push_repo import (
    find_workspace_live_push,
    resolve_push_task_titles,
)
from services.pipeline import github_export_service, pdf_export_service, spec_clarifier
from services.pipeline.critic import AUDIT_EVENT_CRITIC_DISABLED
from services.pipeline.export_service import (
    ExportNotReadyError,
    build_agent_instruction_export,
    build_export,
)
from services.pipeline.increment_service import (
    IncrementBaselineError,
    IncrementError,
    IncrementGenerationError,
    IncrementModeNotSupportedError,
    increment_service,
)
from services.pipeline.spec_clarifier import ClarificationValidationError
from services.queue import QueueUnavailableError, enqueue
from services.research.research_service import AUDIT_EVENT_BRAVE_RESEARCH_TOGGLED
from services.security.sanitizer import sanitize_text
from services.sharing import public_share_service
from services.sharing.public_share_service import (
    WorkspaceNotFinalisedError,
    WorkspaceNotFoundError,
)
from services.workspace_service import workspace_service

logger = logging.getLogger(__name__)

# Content-Security-Policy applied on the public /p/:slug share page.
# The frontend _headers file and the backend public router both set this
# header so it is enforced regardless of which layer serves the response.
# T-193 — unauthenticated pages that render LLM-generated Markdown need
# an explicit CSP to prevent injected content from loading external scripts.
_PUBLIC_SHARE_CSP = (
    "default-src 'none'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "script-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


async def _workspace_response(
    workspace: Workspace, db: AsyncSession
) -> WorkspaceResponse:
    """Wrap WorkspaceResponse.model_validate with the derived coverage chip.

    Uses derive_coverage_summary from coverage_utils so single-workspace
    endpoints (GET /workspaces/{id}) share the same code path as the batched
    list endpoint.  HF-1 — T-198.  MF-2 — T-206.
    """
    response = WorkspaceResponse.model_validate(workspace)
    response.coverage_summary = await derive_coverage_summary(workspace.id, db)
    return response


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    workspace = await workspace_service.create(user.id, payload, db)
    return WorkspaceResponse.model_validate(workspace)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceResponse]:
    workspaces = await workspace_service.list_for_user(user.id, db)
    # Batch coverage query — O(1) DB queries regardless of workspace count.
    # Replaces the previous N+1 pattern of one query per workspace.
    # HF-1 — T-198.
    coverage_map = await derive_coverage_summaries([w.id for w in workspaces], db)
    logger.debug(
        "workspace_list_query",
        extra={"workspace_count": len(workspaces), "coverage_query_count": 1},
    )
    responses: list[WorkspaceResponse] = []
    for w in workspaces:
        resp = WorkspaceResponse.model_validate(w)
        resp.coverage_summary = coverage_map.get(w.id)
        responses.append(resp)
    return responses


def _trashed_response(workspace: Workspace) -> TrashedWorkspaceResponse:
    """Map a trashed workspace to its response, computing the hard-delete date.

    ``purge_after`` = ``archived_at`` + the applicable retention window: the short
    acked window when the delete recorded an acknowledgment, the conservative
    legacy window otherwise (mirrors the Tier-3 purge predicate, plan §5.2).
    """
    acknowledged = workspace.retention_ack_version is not None
    window_days = (
        settings.retention_trash_days
        if acknowledged
        else settings.retention_legacy_archived_days
    )
    return TrashedWorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        archived_at=workspace.archived_at,
        purge_after=workspace.archived_at + timedelta(days=window_days),
        acknowledged=acknowledged,
    )


# Declared BEFORE ``GET /{id}`` on purpose: ``/{id}`` has no path converter, so it
# would otherwise match the literal segment ``trashed`` and 422 on the UUID parse
# (Starlette matches by declaration order).
@router.get("/trashed", response_model=list[TrashedWorkspaceResponse])
async def list_trashed_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TrashedWorkspaceResponse]:
    """Return the user's trashed workspaces for the "Recently deleted" surface.

    Only rows with a set ``archived_at`` are returned (every archived row has one
    since the 0033 backfill); each carries its computed ``purge_after`` so the UI
    shows the countdown with Restore + Export until then.
    """
    workspaces = await workspace_service.list_trashed(user.id, db)
    return [_trashed_response(w) for w in workspaces if w.archived_at is not None]


@router.get("/{id}", response_model=WorkspaceResponse)
async def get_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    workspace = await workspace_service.get(id, user.id, db)
    return await _workspace_response(workspace, db)


@router.patch("/{id}", response_model=WorkspaceResponse)
async def update_workspace(
    id: UUID,
    payload: WorkspaceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    workspace = await workspace_service.update(
        id,
        user.id,
        payload.name,
        db,
        problem_statement=payload.problem_statement,
        target_agent=payload.target_agent,
    )
    return WorkspaceResponse.model_validate(workspace)


@router.patch("/{id}/critic", response_model=WorkspaceResponse)
async def set_workspace_critic(
    id: UUID,
    payload: WorkspaceCriticToggle,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    """Owner-only toggle of the critic quality gate (T-247).

    workspace_service.get filters by user_id, so a non-owner gets 404 and can
    never flip another user's gate.  Every change writes a structured
    `critic_disabled` audit row naming the actor and the resulting state.
    """
    workspace = await workspace_service.get(id, user.id, db)
    if workspace.disable_critic != payload.disable_critic:
        workspace.disable_critic = payload.disable_critic
        await db.commit()
        await db.refresh(workspace)
        logger.info(
            AUDIT_EVENT_CRITIC_DISABLED,
            extra={
                "audit_event": AUDIT_EVENT_CRITIC_DISABLED,
                "actor_id": str(user.id),
                "workspace_id": str(id),
                "disable_critic": payload.disable_critic,
            },
        )
    return await _workspace_response(workspace, db)


@router.patch("/{id}/research", response_model=WorkspaceResponse)
async def set_workspace_research(
    id: UUID,
    payload: WorkspaceResearchToggle,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    """Owner-only opt-in toggle for Brave web-research enrichment (issue #12).

    workspace_service.get filters by user_id, so a non-owner gets 404 and can
    never flip another user's flag.  Every change writes a structured
    `brave_research_toggled` audit row naming the actor and the resulting state —
    the third-party-egress consent decision must be auditable.  Enabling here only
    grants permission; generation still degrades to no-research on any failure or
    insufficient-credit path, so this never affects whether a stage can generate.
    """
    workspace = await workspace_service.get(id, user.id, db)
    if workspace.brave_research_enabled != payload.brave_research_enabled:
        workspace.brave_research_enabled = payload.brave_research_enabled
        await db.commit()
        await db.refresh(workspace)
        logger.info(
            AUDIT_EVENT_BRAVE_RESEARCH_TOGGLED,
            extra={
                "audit_event": AUDIT_EVENT_BRAVE_RESEARCH_TOGGLED,
                "actor_id": str(user.id),
                "workspace_id": str(id),
                "brave_research_enabled": payload.brave_research_enabled,
            },
        )
    return await _workspace_response(workspace, db)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    ack_version: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "The retention-policy version the delete dialog displayed "
            "(from GET /retention/policy). Recorded as proof the user saw the "
            "trash notice; its presence uses the short trash window for the "
            "eventual hard-delete (a stale SPA omitting it falls into the "
            "conservative legacy window)."
        ),
    ),
) -> None:
    """Move a workspace to the trash (issue #43).

    Response is unchanged (204). The workspace becomes invisible to the normal
    list but appears under GET /workspaces/trashed with a restore/export window;
    the Tier-3 worker cron hard-deletes it only after that window elapses.
    """
    await workspace_service.archive(id, user.id, db, ack_version=ack_version)


@router.post("/{id}/restore", response_model=WorkspaceResponse)
async def restore_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    """Restore a trashed workspace to active (issue #43).

    Clears the purge clock so it is no longer eligible for hard-delete. Allowed
    even at the active-workspace quota — it is the user's own data returning.
    404 when not owned by the caller.
    """
    workspace = await workspace_service.restore(id, user.id, db)
    return await _workspace_response(workspace, db)


# _get_redis removed — inject redis via Depends(get_redis).  H-1 — T-177.


@router.post(
    "/{id}/clarify",
    response_model=ClarifyResponse,
    responses={204: {"description": "Judge model unavailable; client should bypass."}},
)
async def request_spec_clarification(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Ask the cheap judge model for 3–5 clarifying questions (Phase 14).

    Best-effort: if the judge model errors or times out, returns 204 so
    the frontend silently bypasses the clarification modal and falls
    through to the standard generate path. The call is free — no
    credit deduction. Rate-limited to 6 calls/user/hour by the
    middleware.
    """
    workspace = await workspace_service.get(id, user.id, db)
    # Shared pool — no manual close needed.  H-1 — T-177.
    questions = await spec_clarifier.request_clarifying_questions(workspace, redis)
    if not questions:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return Response(
        content=ClarifyResponse(questions=questions).model_dump_json(),
        media_type="application/json",
    )


@router.patch("/{id}/clarify", status_code=status.HTTP_204_NO_CONTENT)
async def persist_spec_clarification(
    id: UUID,
    payload: ClarifySubmitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Persist the user's clarification answers.

    ``mode="round"`` validates against the most recent Redis-backed
    clarification round. ``mode="existing"`` validates against already-saved
    workspace questions so a SPEC retry can edit prior answers without calling
    the clarification judge model again. Each answer is sanitised and
    prompt-injection-scanned before persistence.
    """
    # Authorise — calling .get() raises 404 if the workspace isn't the user's.
    workspace = await workspace_service.get(id, user.id, db)
    # Shared pool — no manual close needed.  H-1 — T-177.
    try:
        await spec_clarifier.persist_answers(
            workspace_id=id,
            answers=[a.model_dump() for a in payload.answers],
            db=db,
            redis=redis,
            mode=payload.mode,
            workspace=workspace,
        )
    except ClarificationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{id}/export")
async def export_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        zip_bytes = await build_export(id, user.id, db)
    except ExportNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": (f'attachment; filename="specforge-{id}.zip"')},
    )


@router.get("/{id}/export/agent-instructions/{target}")
async def export_agent_instructions(
    id: UUID,
    target: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if target not in {"codex", "claude_code", "both"}:
        raise HTTPException(status_code=404, detail="Unsupported instruction target")
    try:
        content, filename, media_type = await build_agent_instruction_export(
            id, user.id, db, target
        )
    except ExportNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{id}/export/pdf")
async def export_workspace_pdf(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render the workspace's finalised SPEC/PLAN/TASKS into a branded PDF.

    The HARNESS directory is intentionally excluded — PDFs are for human
    audiences. Rate-limited to 10/user/hour by the middleware.
    """
    try:
        pdf_bytes, slug = await pdf_export_service.render(id, user.id, db)
    except ExportNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="specforge-{slug}.pdf"',
        },
    )


@router.post(
    "/{id}/export/github",
    response_model=GitHubExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_workspace_to_github(
    id: UUID,
    payload: GitHubExportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GitHubExportResponse:
    """Enqueue a GitHub App export of a finalised workspace; return 202.

    All GitHub I/O runs on the durable worker (T-269): this handler resolves and
    owner-checks the target installation, creates/resets the ``pending`` push
    row, enqueues the ``export_push`` job keyed by ``push_id`` (so a duplicate
    submit dedups), and returns ``202`` with the ``push_id`` to poll. It never
    blocks on GitHub.

    **Legacy v1-OAuth users** have no ``GitHubInstallation`` and cannot form this
    request (it requires ``installation_id``); they are prompted to install the
    GitHub App. The Phase-13 synchronous ``push_to_github`` path is retained in
    the codebase for the flagged legacy path but is not driven by this route.

    Fails closed: if the queue is unreachable the push is marked failed and a
    503 is returned — never an inline synchronous fallback.
    """
    # 1. Resolve + owner-check the target installation (confused-deputy guard).
    installation = await github_export_service.load_owned_installation(
        db, payload.installation_id, user.id
    )
    if installation is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Install the GitHub App and choose an installation you own.",
        )
    if installation.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This GitHub App installation is suspended. Re-enable it on GitHub.",
        )

    # 2. Validate + create/reset the pending push row (no GitHub I/O here).
    try:
        push = await github_export_service.prepare_export_push(
            db,
            workspace_id=id,
            user_id=user.id,
            installation=installation,
            export_mode=payload.export_mode,
        )
    except ExportNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except github_export_service.GitHubRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="GitHub API rate limit exceeded.",
        ) from exc
    except github_export_service.GitHubAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub API request failed.",
        ) from exc

    # 3. Enqueue off the request path. job_id = push_id dedups duplicate submits.
    try:
        await enqueue(
            "export_push",
            str(push.id),
            payload.repo_name,
            payload.visibility,
            job_id=str(push.id),
        )
    except QueueUnavailableError as exc:
        await github_export_service.mark_push_unstarted(db, push)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing is unavailable; export was not started.",
        ) from exc

    return GitHubExportResponse(
        push_id=push.id,
        status=push.status,
        repo_full_name=push.repo_full_name,
        repo_url=push.repo_url,
        issue_count=0,
    )


@router.get(
    "/{id}/export/github",
    response_model=IntegrationPushRead,
)
async def get_workspace_github_push(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IntegrationPushRead:
    """Return the most recent GitHub push for this workspace, or 404 if none.

    Workspace ownership is asserted by the export service's underlying
    query (filters by ``(workspace_id, user_id)``) so the response is 404
    both when no push exists and when the workspace belongs to another
    user — never 403 — to avoid leaking workspace existence.
    """
    push = await github_export_service.get_push(
        workspace_id=id,
        user_id=user.id,
        db=db,
    )
    if push is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GitHub push found for this workspace.",
        )
    return IntegrationPushRead(
        id=push.id,
        status=push.status,
        repo_full_name=push.repo_full_name,
        repo_url=push.repo_url,
        issue_count=int(getattr(push, "issue_count", 0) or 0),
        installation_id=push.installation_id,
        pushed_at=push.pushed_at,
        created_at=push.created_at,
    )


# ---------------------------------------------------------------------------
# GitHub bidirectional sync (Phase 21 — T-273). Owner-scoped; all GitHub I/O
# runs on the worker (resync/backfill return 202). Routes:
#   GET  /workspaces/{id}/sync          — live task-completion + drift
#   POST /workspaces/{id}/sync/resync   — re-push changed tasks' issues (202)
#   POST /workspaces/{id}/sync/backfill — recover missed events (202)
# ---------------------------------------------------------------------------


@router.get("/{id}/sync", response_model=SyncStateResponse)
async def get_workspace_sync(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SyncStateResponse:
    """Return the workspace's live GitHub task-completion + drift state.

    ``out_of_sync`` is the persisted drift signal: re-finalising Tasks marks the
    push ``stale`` (T-273 drift hook), which surfaces here. 404 when the
    workspace is not owned by the caller or has no live push (never 403, so
    workspace existence is not leaked).
    """
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    push = await find_workspace_live_push(db, id)
    if push is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GitHub push found for this workspace.",
        )
    tasks = list(
        (
            await db.execute(
                select(IntegrationPushTask).where(
                    IntegrationPushTask.push_id == push.id
                )
            )
        ).scalars()
    )
    shipped = sum(1 for t in tasks if t.state == "done")
    # Resolve human T-NNN/title from the push's source Tasks version so the UI
    # shows a real task identity instead of the opaque content-hash task_ref.
    titles = await resolve_push_task_titles(db, push)

    def _to_state(t: IntegrationPushTask) -> TaskSyncState:
        state = TaskSyncState.model_validate(t)
        human_ref, title = titles.get(t.task_ref, (None, None))
        state.human_ref = human_ref
        state.title = title
        return state

    return SyncStateResponse(
        push_id=push.id,
        status=push.status,
        out_of_sync=(push.status == "stale"),
        shipped=shipped,
        total=len(tasks),
        tasks=[_to_state(t) for t in tasks],
    )


@router.post(
    "/{id}/sync/resync",
    response_model=PushStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resync_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushStatusResponse:
    """Re-sync the workspace's GitHub issues to the current spec (202).

    Resets the live push to ``pending`` and enqueues ``export_push`` (keyed by
    push_id), which idempotently updates each existing task's issue in place and
    creates issues for any new tasks. Fails closed (503) if the queue is down.
    """
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    push = await find_workspace_live_push(db, id)
    if push is None or push.repo_full_name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GitHub push to re-sync for this workspace.",
        )
    # Remember the live status so a transient enqueue failure can restore it
    # rather than failing an already-healthy push (audit #3).
    previous_status = push.status
    push.status = "pending"
    await db.commit()
    repo_name = push.repo_full_name.split("/")[-1]
    try:
        await enqueue(
            "export_push", str(push.id), repo_name, "private", job_id=str(push.id)
        )
    except QueueUnavailableError as exc:
        # A queue blip during resync must NOT drop the live push and its
        # bidirectional sync — restore the prior status (completed/stale).
        await github_export_service.restore_push_status(db, push, previous_status)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing is unavailable; re-sync was not started.",
        ) from exc
    await db.refresh(push)
    return PushStatusResponse.model_validate(push)


@router.post(
    "/{id}/sync/backfill",
    response_model=PushStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def backfill_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushStatusResponse:
    """Recover task states from GitHub's issues list (202).

    Enqueues ``backfill_repo`` to reconcile closures/reopens missed while the
    worker was down. Idempotent with the webhook reconcile path.
    """
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    push = await find_workspace_live_push(db, id)
    if push is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GitHub push to backfill for this workspace.",
        )
    try:
        await enqueue("backfill_repo", str(push.id))
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing is unavailable; backfill was not started.",
        ) from exc
    return PushStatusResponse.model_validate(push)


# ---------------------------------------------------------------------------
# Increments timeline + idea backlog (Phase 21 — T-280). Owner-scoped. Generation
# (POST /increments) runs the T-279 delta synchronously and is credit-aware; the
# GitHub push (POST /increments/{inc_id}/push) enqueues the worker and returns
# 202. Routes:
#   GET  /workspaces/{id}/increments                — timeline, newest first
#   POST /workspaces/{id}/increments                — generate a delta (T-279)
#   POST /workspaces/{id}/increments/{inc_id}/push  — enqueue increment_push (202)
#   GET  /workspaces/{id}/ideas                     — backlog, newest first
#   POST /workspaces/{id}/ideas                     — capture a user idea
# ---------------------------------------------------------------------------


@router.get("/{id}/increments", response_model=list[IncrementRead])
async def list_increments(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[IncrementRead]:
    """Return the workspace's increment timeline, newest first (owner-scoped)."""
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    rows = (
        (
            await db.execute(
                select(Increment)
                .where(Increment.workspace_id == id)
                .order_by(Increment.sequence.desc())
            )
        )
        .scalars()
        .all()
    )
    return [IncrementRead.model_validate(r) for r in rows]


@router.post(
    "/{id}/increments",
    response_model=IncrementGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_increment(
    id: UUID,
    payload: IncrementCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IncrementGenerateResponse:
    """Generate a delta increment from a feature request (T-279).

    Synchronous + credit-aware: the baseline (finalised stages) is immutable
    context and the output is appended to TASKS.md as a new version with stable
    ``task_ref``s. Returns the new increment plus the count of appended tasks. The
    GitHub push is a separate 202 call.

    Errors map to: 404 (not owned), 409 (workspace not finalised / mode gated
    off), 402 (insufficient credits), 422 (no delta produced).
    """
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    try:
        result = await increment_service.generate_increment(
            id, payload.feature_request, user, db, mode=payload.mode
        )
    except IncrementBaselineError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except IncrementModeNotSupportedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except InsufficientCreditsError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
        ) from exc
    except IncrementGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except IncrementError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    increment = (
        await db.execute(select(Increment).where(Increment.id == result.increment_id))
    ).scalar_one()
    response = IncrementGenerateResponse.model_validate(increment)
    response.new_task_count = len(result.new_tasks)
    return response


@router.post(
    "/{id}/increments/{inc_id}/push",
    response_model=IncrementPushResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def push_increment(
    id: UUID,
    inc_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IncrementPushResponse:
    """Enqueue an incremental GitHub sync for the increment (202).

    Pushes only the new issues under a new milestone (and, in pr_with_tests mode,
    one PR), layered on already-shipped work. ``job_id=inc_id`` dedups a
    double-submit. Requires a finalised increment and a live baseline push; fails
    closed (503) if the queue is down.
    """
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    increment = (
        await db.execute(
            select(Increment).where(
                Increment.id == inc_id, Increment.workspace_id == id
            )
        )
    ).scalar_one_or_none()
    if increment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Increment not found."
        )
    if increment.status in ("draft", "generating"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Increment is not ready to push.",
        )
    push = await find_workspace_live_push(db, id)
    if push is None or push.repo_full_name is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect and export this workspace to GitHub before pushing an "
            "increment.",
        )
    try:
        await enqueue("increment_push", str(inc_id), job_id=str(inc_id))
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing is unavailable; increment push was not "
            "started.",
        ) from exc
    return IncrementPushResponse(increment_id=inc_id, status=increment.status)


@router.get("/{id}/ideas", response_model=list[IdeaRead])
async def list_ideas(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[IdeaRead]:
    """Return the workspace's idea backlog, newest first (owner-scoped).

    Includes both user-captured ideas and ones flowed back from GitHub issues
    labelled ``idea``/``enhancement`` via the reconcile path (T-272/T-280).
    """
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    rows = (
        (
            await db.execute(
                select(IncrementIdea)
                .where(IncrementIdea.workspace_id == id)
                .order_by(IncrementIdea.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [IdeaRead.model_validate(r) for r in rows]


@router.post(
    "/{id}/ideas",
    response_model=IdeaRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_idea(
    id: UUID,
    payload: IdeaCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IdeaRead:
    """Capture a mid-build feature idea into the workspace backlog (source=user).

    The free-text idea is sanitised with the same policy as public share / PDF
    before persistence.
    """
    await workspace_service.get(id, user.id, db)  # 404 if not owned
    text = sanitize_text(payload.text).strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idea text is empty after sanitisation.",
        )
    idea = IncrementIdea(
        workspace_id=id,
        source="user",
        external_ref=None,
        text=text,
        status="open",
    )
    db.add(idea)
    await db.commit()
    await db.refresh(idea)
    return IdeaRead.model_validate(idea)


# ---------------------------------------------------------------------------
# T-USE-09: public share lifecycle (T-168). Three thin endpoints that
# delegate to public_share_service. The 409 path covers a workspace whose
# pipeline isn't fully finalised; ownership is asserted by workspace_service.
# ---------------------------------------------------------------------------


def _share_url(slug: str) -> str:
    """Build the absolute public URL the frontend will surface."""
    base = settings.frontend_url.rstrip("/")
    return f"{base}/p/{slug}"


@router.post("/{id}/share", response_model=ShareLinkResponse)
async def enable_public_share(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> ShareLinkResponse:
    # Authorise — get() raises 404 if not owned by caller.
    await workspace_service.get(id, user.id, db)
    try:
        slug = await public_share_service.enable(id, db, redis)
    except WorkspaceNotFinalisedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "workspace_not_finalised", "message": str(exc)},
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_found"
        ) from exc
    return ShareLinkResponse(slug=slug, url=_share_url(slug), enabled=True)


@router.delete("/{id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def disable_public_share(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Response:
    await workspace_service.get(id, user.id, db)
    try:
        await public_share_service.disable(id, db, redis)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{id}/share/rotate", response_model=ShareLinkResponse)
async def rotate_public_share(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> ShareLinkResponse:
    await workspace_service.get(id, user.id, db)
    try:
        slug = await public_share_service.rotate(id, db, redis)
    except WorkspaceNotFinalisedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "workspace_not_finalised", "message": str(exc)},
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_found"
        ) from exc
    return ShareLinkResponse(slug=slug, url=_share_url(slug), enabled=True)

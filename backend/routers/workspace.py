import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import get_current_user
from models import User
from schemas.integration import (
    GitHubExportRequest,
    GitHubExportResponse,
    IntegrationPushRead,
)
from schemas.workspace import (
    ClarifyResponse,
    ClarifySubmitRequest,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from services.integrations.github_api_client import (
    GitHubAPIError,
    GitHubNotConnectedError,
    GitHubRateLimitError,
    GitHubRepoExistsError,
    GitHubTokenExpiredError,
)
from services.llm.provider_status import is_provider_configured
from services.pipeline import github_export_service, spec_clarifier
from services.pipeline.export_service import ExportNotReadyError, build_export
from services.pipeline.spec_clarifier import ClarificationValidationError
from services.workspace_service import workspace_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    if not is_provider_configured(payload.provider):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "provider_not_configured",
                "message": "This provider is not configured on the backend.",
            },
        )
    workspace = await workspace_service.create(user.id, payload, db)
    return WorkspaceResponse.model_validate(workspace)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceResponse]:
    workspaces = await workspace_service.list_for_user(user.id, db)
    return [WorkspaceResponse.model_validate(w) for w in workspaces]


@router.get("/{id}", response_model=WorkspaceResponse)
async def get_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    workspace = await workspace_service.get(id, user.id, db)
    return WorkspaceResponse.model_validate(workspace)


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
    )
    return WorkspaceResponse.model_validate(workspace)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_workspace(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await workspace_service.archive(id, user.id, db)


def _get_redis() -> Redis:
    """Construct a per-request Redis client.

    The clarify endpoints touch Redis once (read/write the round key)
    and have no need for the long-lived application singleton.
    """
    return Redis.from_url(settings.redis_url, decode_responses=True)


@router.post(
    "/{id}/clarify",
    response_model=ClarifyResponse,
    responses={204: {"description": "Judge model unavailable; client should bypass."}},
)
async def request_spec_clarification(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Ask the cheap judge model for 3–5 clarifying questions (Phase 14).

    Best-effort: if the judge model errors or times out, returns 204 so
    the frontend silently bypasses the clarification modal and falls
    through to the standard generate path. The call is free — no
    credit deduction. Rate-limited to 6 calls/user/hour by the
    middleware.
    """
    workspace = await workspace_service.get(id, user.id, db)
    redis = _get_redis()
    try:
        questions = await spec_clarifier.request_clarifying_questions(workspace, redis)
    finally:
        await redis.close()
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
) -> Response:
    """Persist the user's answers to the most recent clarification round.

    Returns 400 if any submitted question is not in the cached round
    (the user must answer the questions they were shown, not arbitrary
    text). Each answer is sanitised and prompt-injection-scanned before
    persistence.
    """
    # Authorise — calling .get() raises 404 if the workspace isn't the user's.
    await workspace_service.get(id, user.id, db)
    redis = _get_redis()
    try:
        await spec_clarifier.persist_answers(
            workspace_id=id,
            answers=[a.model_dump() for a in payload.answers],
            db=db,
            redis=redis,
        )
    except ClarificationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        ) from exc
    finally:
        await redis.close()
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
    """Push a finalised workspace to a new GitHub repository.

    Idempotent: re-export updates files in place and updates existing
    issues rather than creating duplicates. The rate-limit middleware
    caps this endpoint at 3 successful POSTs per user per hour.
    """
    try:
        push = await github_export_service.push_to_github(
            workspace_id=id,
            user_id=user.id,
            repo_name=payload.repo_name,
            visibility=payload.visibility,
            db=db,
        )
    except GitHubNotConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GitHub not connected. Connect from Settings.",
        ) from exc
    except GitHubTokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GitHub connection expired. Reconnect from Settings.",
        ) from exc
    except GitHubRepoExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A repo with that name already exists in your GitHub account.",
        ) from exc
    except GitHubRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="GitHub API rate limit reached. Wait a few minutes and try again.",
        ) from exc
    except ExportNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except GitHubAPIError as exc:
        logger.warning(
            "github_export.api_error",
            extra={"github_status": exc.status, "github_message": exc.message},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned an unexpected error.",
        ) from exc

    issue_count = getattr(push, "issue_count", 0) or 0
    return GitHubExportResponse(
        push_id=push.id,
        status=push.status,
        repo_full_name=push.repo_full_name,
        repo_url=push.repo_url,
        issue_count=int(issue_count),
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
        pushed_at=push.pushed_at,
        created_at=push.created_at,
    )

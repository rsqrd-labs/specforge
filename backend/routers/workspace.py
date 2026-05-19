import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from models import User
from schemas.integration import (
    GitHubExportRequest,
    GitHubExportResponse,
    IntegrationPushRead,
)
from schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from services.integrations.github_api_client import (
    GitHubAPIError,
    GitHubNotConnectedError,
    GitHubRateLimitError,
    GitHubRepoExistsError,
    GitHubTokenExpiredError,
)
from services.llm.provider_status import is_provider_configured
from services.pipeline import github_export_service
from services.pipeline.export_service import ExportNotReadyError, build_export
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

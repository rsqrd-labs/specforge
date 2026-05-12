from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from models import User
from schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate
from services.llm.provider_status import is_provider_configured
from services.pipeline.export_service import ExportNotReadyError, build_export
from services.workspace_service import workspace_service

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

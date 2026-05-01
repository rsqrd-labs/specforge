from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Stage, Workspace
from schemas.workspace import WorkspaceCreate
from services.security.sanitizer import sanitize_text

_STAGE_ORDER = ["spec", "plan", "harness", "tasks"]


class WorkspaceService:
    async def create(
        self, user_id: UUID, payload: WorkspaceCreate, db: AsyncSession
    ) -> Workspace:
        workspace = Workspace(
            user_id=user_id,
            name=sanitize_text(payload.name),
            problem_statement=sanitize_text(payload.problem_statement),
            provider=payload.provider,
            model=payload.model,
            status="active",
        )
        db.add(workspace)
        await db.flush()

        for stage_type in _STAGE_ORDER:
            db.add(
                Stage(
                    workspace_id=workspace.id,
                    type=stage_type,
                    status="draft" if stage_type == "spec" else "locked",
                    content=None,
                    current_version=0,
                    review_gate_acknowledged=False,
                )
            )

        await db.commit()
        return await self._load(workspace.id, db)

    async def list_for_user(self, user_id: UUID, db: AsyncSession) -> list[Workspace]:
        result = await db.execute(
            select(Workspace)
            .where(Workspace.user_id == user_id, Workspace.status == "active")
            .options(selectinload(Workspace.stages))
            .order_by(Workspace.created_at.desc())
        )
        return list(result.scalars())

    async def get(
        self, workspace_id: UUID, user_id: UUID, db: AsyncSession
    ) -> Workspace:
        result = await db.execute(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .options(selectinload(Workspace.stages))
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
            )
        if workspace.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
            )
        return workspace

    async def update(
        self, workspace_id: UUID, user_id: UUID, name: str, db: AsyncSession
    ) -> Workspace:
        workspace = await self.get(workspace_id, user_id, db)
        workspace.name = sanitize_text(name)
        await db.commit()
        await db.refresh(workspace)
        return workspace

    async def archive(
        self, workspace_id: UUID, user_id: UUID, db: AsyncSession
    ) -> None:
        workspace = await self.get(workspace_id, user_id, db)
        workspace.status = "archived"
        await db.commit()

    async def _load(self, workspace_id: UUID, db: AsyncSession) -> Workspace:
        result = await db.execute(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .options(selectinload(Workspace.stages))
        )
        return result.scalar_one()


workspace_service = WorkspaceService()

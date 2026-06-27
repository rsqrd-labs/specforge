from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from models import Stage, User, Workspace
from schemas.workspace import WorkspaceCreate
from services.llm.routing import LLMRoutingError, resolve_llm_route
from services.security.problem_statement_gate import (
    ProblemStatementValidationError,
    assert_valid_problem_statement,
)
from services.security.sanitizer import sanitize_text

_STAGE_ORDER = ["spec", "plan", "harness", "tasks"]


class WorkspaceService:
    async def create(
        self, user_id: UUID, payload: WorkspaceCreate, db: AsyncSession
    ) -> Workspace:
        self._assert_problem_statement_is_valid(payload.problem_statement)
        server_model = self._server_default_model(payload.provider)
        mode, target_agent, time_budget_minutes = self._resolve_mode(payload)

        # Lock the user row so concurrent create requests are serialized and
        # the quota check + insert are atomic within this transaction.
        await db.execute(select(User).where(User.id == user_id).with_for_update())
        active_count = await self._active_workspace_count(user_id, db)
        if active_count >= settings.max_active_workspaces_per_user:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "workspace_quota_exceeded",
                    "limit": settings.max_active_workspaces_per_user,
                },
            )

        workspace = Workspace(
            user_id=user_id,
            name=sanitize_text(payload.name),
            problem_statement=sanitize_text(payload.problem_statement),
            provider=payload.provider,
            model=server_model,
            status="active",
            mode=mode,
            target_agent=target_agent,
            time_budget_minutes=time_budget_minutes,
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
        result = await db.execute(
            select(Workspace)
            .where(Workspace.id == workspace.id)
            .options(selectinload(Workspace.stages))
        )
        return result.scalar_one()

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
            .where(Workspace.id == workspace_id, Workspace.user_id == user_id)
            .options(selectinload(Workspace.stages))
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
            )
        return workspace

    async def update(
        self,
        workspace_id: UUID,
        user_id: UUID,
        name: str | None,
        db: AsyncSession,
        problem_statement: str | None = None,
    ) -> Workspace:
        workspace = await self.get(workspace_id, user_id, db)
        if name is not None:
            workspace.name = sanitize_text(name)
        if problem_statement is not None:
            self._assert_problem_statement_is_valid(problem_statement)
            workspace.problem_statement = sanitize_text(problem_statement)
            self._mark_problem_statement_dependents_stale(workspace)
        await db.commit()
        await db.refresh(workspace)
        return workspace

    def _mark_problem_statement_dependents_stale(self, workspace: Workspace) -> None:
        for stage in workspace.stages:
            if stage.type == "spec" and stage.content and stage.status == "finalised":
                stage.status = "stale"
            elif stage.type != "spec" and stage.status == "finalised":
                stage.status = "stale"

    async def archive(
        self, workspace_id: UUID, user_id: UUID, db: AsyncSession
    ) -> None:
        workspace = await self.get(workspace_id, user_id, db)
        workspace.status = "archived"
        await db.commit()

    async def _active_workspace_count(self, user_id: UUID, db: AsyncSession) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(Workspace)
            .where(Workspace.user_id == user_id, Workspace.status == "active")
        )
        return int(result.scalar() or 0)

    def _assert_problem_statement_is_valid(self, problem_statement: str) -> None:
        try:
            assert_valid_problem_statement(problem_statement)
        except ProblemStatementValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": exc.result.code,
                    "message": exc.result.message,
                    "hints": exc.result.hints,
                },
            ) from exc

    def _resolve_mode(
        self, payload: WorkspaceCreate
    ) -> tuple[str, str | None, int | None]:
        """Resolve the persisted (mode, target_agent, time_budget_minutes).

        The ``demo_day_mode_enabled`` config flag is the master server-side gate
        (plan §4/§0): when it is off, ``mode`` is forced to ``"standard"`` and the
        Demo-Day-only metadata is dropped, so a client cannot opt a workspace into
        Demo Day mode before the feature is enabled and the standard create path
        stays byte-identical. The schema already guarantees ``target_agent`` is
        present when ``mode == "demo_day"`` and absent otherwise.
        """
        if not settings.demo_day_mode_enabled or payload.mode != "demo_day":
            return "standard", None, None
        return "demo_day", payload.target_agent, payload.time_budget_minutes

    def _server_default_model(self, provider: str) -> str:
        try:
            route = resolve_llm_route(
                operation="spec.generate",
                preferred_provider=provider,
                requested_tier="mid",
                fallback_tier=None,
                latency_class="interactive",
            )
        except LLMRoutingError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "provider_route_unavailable",
                    "message": "This provider cannot currently route generation work.",
                },
            ) from exc
        return route.model


workspace_service = WorkspaceService()

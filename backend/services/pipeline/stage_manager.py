from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from middleware.rate_limit import sliding_window_check
from models import EvalResult, Stage, StageVersion, Workspace
from schemas.stage import DiffResponse, RefineRequest
from services.credit_service import credit_service
from services.evals.online_eval import run_eval_background
from services.llm.base import ProviderError
from services.llm.gateway import get_llm
from services.llm.provider_config import JUDGE_MODELS
from services.pipeline.diff_engine import apply_diff, compute_diff
from services.pipeline.prompt_builder import build_prompt
from services.security.output_validator import validate
from services.security.prompt_guard import scan

logger = logging.getLogger(__name__)

STAGE_ORDER = ["spec", "plan", "harness", "tasks"]


def _log_eval_error(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        logger.error("eval_background_failed", extra={"error": str(exc)})


def _eval_to_dict(result: EvalResult) -> dict:
    return {
        "id": str(result.id),
        "stage_version_id": str(result.stage_version_id),
        "stage_type": result.stage_type,
        "overall_score": result.overall_score,
        "completeness": result.completeness,
        "clarity": result.clarity,
        "coverage_percent": result.coverage_percent,
        "uncovered_reqs": result.uncovered_reqs,
        "tasks_without_ref": result.tasks_without_ref,
        "flagged": result.flagged,
        "created_at": result.created_at.isoformat(),
    }


STAGE_DEPENDENCIES: dict[str, list[str]] = {
    "spec": [],
    "plan": ["spec"],
    "harness": ["spec", "plan"],
    "tasks": ["spec", "plan", "harness"],
}
CREDIT_COSTS = {"generate": 10, "refine": 3, "regenerate": 10}
_STAGE_CACHE_PREFIX = "stage:"
_STAGE_CACHE_TTL = 3600


class StageDependencyError(Exception):
    pass


class SecurityError(Exception):
    pass


class RefineSelectionError(Exception):
    pass


class RateLimitError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"LLM rate limit exceeded. Retry after {retry_after}s.")
        self.retry_after = retry_after


class StageManager:
    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis: Redis | None = redis_client

    async def _redis_client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def generate(
        self, stage_id: UUID, user, db: AsyncSession
    ) -> AsyncGenerator[str, None]:
        stage = await self._load_stage(stage_id, db)
        workspace = await self._load_workspace(stage.workspace_id, db)

        if stage.status not in ("draft", "stale"):
            raise ValueError(f"Stage status {stage.status!r} is not generatable")

        await self._assert_dependencies_finalised(stage.type, workspace.id, db)

        scan_result = scan(workspace.problem_statement)
        if not scan_result.is_safe:
            raise SecurityError(
                f"Problem statement flagged: {scan_result.matched_pattern}"
            )

        redis = await self._redis_client()
        if not await sliding_window_check(redis, f"llm:{user.id}", 10, 60):
            raise RateLimitError(retry_after=60)
        if not await sliding_window_check(redis, f"llm_daily:{user.id}", 200, 86400):
            raise RateLimitError(retry_after=86400)

        deduction = await credit_service.deduct(
            db, user.id, CREDIT_COSTS["generate"], "generate"
        )

        stage.status = "in_progress"
        stage.deduction_ledger_id = deduction.id
        stage.updated_at = datetime.now(UTC)
        await db.commit()

        system_prompt, user_prompt = await build_prompt(
            stage.type, workspace, db, redis
        )

        accumulated = ""
        try:
            adapter = get_llm(workspace.provider, workspace.model)
            async for token in adapter.stream(
                system_prompt, user_prompt, max_tokens=8192
            ):
                accumulated += token
                yield token
        except ProviderError as exc:
            await credit_service.refund(db, deduction.id)
            stage.status = "draft"
            stage.updated_at = datetime.now(UTC)
            await db.commit()
            raise exc

        validation = validate(accumulated)
        if not validation.is_safe:
            await credit_service.refund(db, deduction.id)
            stage.status = "draft"
            stage.updated_at = datetime.now(UTC)
            await db.commit()
            raise SecurityError(f"Output failed validation: {validation.reason}")

        stage.content = accumulated
        stage.current_version += 1
        stage.status = "draft"
        stage.updated_at = datetime.now(UTC)
        version = StageVersion(
            stage_id=stage.id,
            version=stage.current_version,
            content=accumulated,
            created_by="ai",
        )
        db.add(version)
        await db.flush()
        version_id = version.id
        spec_content = ""
        if stage.type != "spec":
            spec_content = (
                await redis.get(f"{_STAGE_CACHE_PREFIX}{workspace.id}:spec") or ""
            )
        await db.commit()
        await self._invalidate_stage_cache(workspace.id, stage.type, redis)
        eval_task = asyncio.create_task(
            run_eval_background(
                version_id,
                stage.type,
                accumulated,
                spec_content,
                workspace.provider,
                JUDGE_MODELS[workspace.provider],
            )
        )
        eval_task.add_done_callback(_log_eval_error)
        yield f'{{"done": true, "stage_id": "{stage_id}"}}'

        try:
            eval_result = await asyncio.wait_for(
                asyncio.shield(eval_task), timeout=30.0
            )
            if eval_result is not None:
                yield json.dumps({"eval": _eval_to_dict(eval_result)})
        except (asyncio.TimeoutError, Exception):
            pass

    async def refine(
        self, stage_id: UUID, request: RefineRequest, user, db: AsyncSession
    ) -> DiffResponse:
        stage = await self._load_stage(stage_id, db)
        workspace = await self._load_workspace(stage.workspace_id, db)

        for label, text in (
            ("instruction", request.instruction),
            ("selected_text", request.selected_text),
        ):
            scan_result = scan(text)
            if not scan_result.is_safe:
                raise SecurityError(
                    f"Refine {label} flagged: {scan_result.matched_pattern}"
                )

        redis = await self._redis_client()
        if not await sliding_window_check(redis, f"llm:{user.id}", 10, 60):
            raise RateLimitError(retry_after=60)
        if not await sliding_window_check(redis, f"llm_daily:{user.id}", 200, 86400):
            raise RateLimitError(retry_after=86400)

        content = stage.content or ""
        if request.selection_end > len(content):
            raise RefineSelectionError("Selected range is outside the current document")
        if (
            content[request.selection_start:request.selection_end]
            != request.selected_text
        ):
            raise RefineSelectionError("Selected text no longer matches the document")

        doc_len = len(content)
        selection_len = request.selection_end - request.selection_start
        large_selection = doc_len > 0 and (selection_len / doc_len) > 0.80

        system_prompt = (
            "You are SpecForge. Rewrite only the selected text per the instruction. "
            "Return ONLY the replacement text, nothing else."
        )
        user_prompt = (
            f"Current document:\n{content}\n\n"
            f"Selected text:\n{request.selected_text}\n\n"
            f"Instruction: {request.instruction}\n\n"
            "Provide the replacement text only."
        )

        adapter = get_llm(workspace.provider, workspace.model)
        try:
            replacement = await adapter.complete(
                system_prompt, user_prompt, max_tokens=4096
            )
        except Exception:
            raise

        validation = validate(replacement)
        if not validation.is_safe:
            raise SecurityError(f"Refine output failed validation: {validation.reason}")

        proposed = apply_diff(
            content,
            request.selection_start,
            request.selection_end,
            replacement,
        )
        diff = compute_diff(content, proposed)

        return DiffResponse(
            diff=diff,
            original=content,
            proposed=proposed,
            large_selection=large_selection,
        )

    async def finalise(self, stage_id: UUID, user, db: AsyncSession) -> Stage:
        stage = await self._load_stage(stage_id, db)
        if stage.status != "draft":
            raise ValueError(f"Stage status {stage.status!r} cannot be finalised")

        stage.status = "finalised"
        stage.finalised_at = datetime.now(UTC)
        stage.updated_at = datetime.now(UTC)

        next_stage = await self._get_next_stage(stage, db)
        if next_stage and next_stage.status == "locked":
            next_stage.status = "draft"
            next_stage.updated_at = datetime.now(UTC)

        redis = await self._redis_client()
        await self._invalidate_stage_cache(stage.workspace_id, stage.type, redis)
        content = stage.content or ""
        await redis.set(
            f"{_STAGE_CACHE_PREFIX}{stage.workspace_id}:{stage.type}",
            content,
            ex=_STAGE_CACHE_TTL,
        )

        await db.commit()
        await db.refresh(stage)
        return stage

    async def rollback(
        self, stage_id: UUID, version_number: int, user, db: AsyncSession
    ) -> Stage:
        result = await db.execute(
            select(StageVersion).where(
                StageVersion.stage_id == stage_id,
                StageVersion.version == version_number,
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Version not found")

        stage = await self._load_stage(stage_id, db)
        stage.content = version.content
        stage.current_version = version_number
        stage.status = "draft"
        stage.updated_at = datetime.now(UTC)

        await self._mark_downstream_stale(stage, db)

        redis = await self._redis_client()
        await self._invalidate_stage_cache(stage.workspace_id, stage.type, redis)
        await db.commit()
        await db.refresh(stage)
        return stage

    async def handle_content_edit(
        self, stage_id: UUID, new_content: str, user, db: AsyncSession
    ) -> Stage:
        stage = await self._load_stage(stage_id, db)
        was_finalised = stage.status == "finalised"

        stage.content = new_content
        stage.current_version += 1
        stage.status = "draft" if not was_finalised else "stale"
        stage.updated_at = datetime.now(UTC)

        version = StageVersion(
            stage_id=stage.id,
            version=stage.current_version,
            content=new_content,
            created_by="user",
        )
        db.add(version)

        if was_finalised:
            stage.status = "stale"
            await self._mark_downstream_stale(stage, db)

        redis = await self._redis_client()
        await self._invalidate_stage_cache(stage.workspace_id, stage.type, redis)
        await db.commit()
        await db.refresh(stage)
        return stage

    async def _mark_downstream_stale(self, stage: Stage, db: AsyncSession) -> None:
        stage_idx = STAGE_ORDER.index(stage.type)
        downstream_types = STAGE_ORDER[stage_idx + 1 :]
        if not downstream_types:
            return

        result = await db.execute(
            select(Stage).where(
                Stage.workspace_id == stage.workspace_id,
                Stage.type.in_(downstream_types),
                Stage.status == "finalised",
            )
        )
        for downstream in result.scalars():
            downstream.status = "stale"
            downstream.updated_at = datetime.now(UTC)

    async def _assert_dependencies_finalised(
        self, stage_type: str, workspace_id: UUID, db: AsyncSession
    ) -> None:
        deps = STAGE_DEPENDENCIES[stage_type]
        if not deps:
            return
        result = await db.execute(
            select(Stage).where(
                Stage.workspace_id == workspace_id,
                Stage.type.in_(deps),
            )
        )
        for dep_stage in result.scalars():
            if dep_stage.status != "finalised":
                raise StageDependencyError(
                    f"Dependency stage {dep_stage.type!r} is not finalised"
                )

    async def _get_next_stage(self, stage: Stage, db: AsyncSession) -> Stage | None:
        idx = STAGE_ORDER.index(stage.type)
        if idx >= len(STAGE_ORDER) - 1:
            return None
        next_type = STAGE_ORDER[idx + 1]
        result = await db.execute(
            select(Stage).where(
                Stage.workspace_id == stage.workspace_id,
                Stage.type == next_type,
            )
        )
        return result.scalar_one_or_none()

    async def _load_stage(self, stage_id: UUID, db: AsyncSession) -> Stage:
        result = await db.execute(select(Stage).where(Stage.id == stage_id))
        stage = result.scalar_one_or_none()
        if stage is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Stage not found")
        return stage

    async def _load_workspace(self, workspace_id: UUID, db: AsyncSession) -> Workspace:
        result = await db.execute(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .options(selectinload(Workspace.stages))
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Workspace not found")
        return workspace

    async def _invalidate_stage_cache(
        self, workspace_id: UUID, stage_type: str, redis: Redis
    ) -> None:
        await redis.delete(f"{_STAGE_CACHE_PREFIX}{workspace_id}:{stage_type}")


stage_manager = StageManager()

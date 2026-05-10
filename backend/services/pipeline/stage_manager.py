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
from prompts.base import SECURITY_AND_PRIVACY_RULES, wrap_untrusted_content
from schemas.stage import DiffResponse, RefineRequest
from services import langfuse_service
from services.credit_service import CREDIT_COSTS, credit_service
from services.evals.online_eval import run_eval_background
from services.llm.base import ProviderError
from services.llm.gateway import get_llm
from services.llm.provider_config import JUDGE_MODELS
from services.pipeline.diff_engine import apply_diff, compute_diff
from services.pipeline.prompt_builder import build_prompt
from services.security.output_validator import validate
from services.security.problem_statement_gate import (
    ProblemStatementValidationError,
    assert_valid_problem_statement,
)
from services.security.prompt_guard import scan
from services.security.sanitizer import sanitize_text

logger = logging.getLogger(__name__)

STAGE_ORDER = ["spec", "plan", "harness", "tasks"]


def _strip_code_fence(text: str) -> str:
    """Strip a wrapping code fence if the LLM wrapped its entire response in one."""
    stripped = text.strip()
    lines = stripped.split("\n")
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


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
_STAGE_CACHE_PREFIX = "stage:"
_STAGE_CACHE_TTL = 3600


class StageDependencyError(Exception):
    pass


class StageStateError(Exception):
    """Raised when generate() is called on a stage whose current status
    does not permit generation (e.g. already in_progress, finalised, locked)."""

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
    STAGE_ORDER = STAGE_ORDER
    STAGE_DEPENDENCIES = {
        "spec": ["problem_statement"],
        "plan": ["spec"],
        "harness": ["spec", "plan"],
        "tasks": ["spec", "plan", "harness"],
    }

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis: Redis | None = redis_client

    async def _redis_client(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def _start_langfuse_span(
        self,
        *,
        trace_id: str,
        workspace: Workspace,
        user,
        stage: Stage,
        action: str,
    ) -> str | None:
        try:
            client = langfuse_service.get_langfuse_client()
            await client.create_trace(
                name=f"workspace.{workspace.id}",
                trace_id=trace_id,
                user_id=str(user.id),
                metadata={
                    "trace_id": trace_id,
                    "workspace_id": str(workspace.id),
                    "user_id": str(user.id),
                    "stage_type": stage.type,
                    "action": action,
                },
            )
            return await client.create_span(
                trace_id=trace_id,
                name=f"stage.{stage.type}.{action}",
                metadata={
                    "workspace_id": str(workspace.id),
                    "stage_type": stage.type,
                    "action": action,
                },
            )
        except Exception:
            logger.exception(
                "langfuse.stage_span_start_failed",
                extra={"stage_id": str(stage.id), "trace_id": trace_id},
            )
            return None

    async def _end_langfuse_span(self, span_id: str | None) -> None:
        try:
            await langfuse_service.get_langfuse_client().end_span(span_id)
        except Exception:
            logger.exception("langfuse.stage_span_end_failed")

    async def _mark_langfuse_span_failed(
        self, span_id: str | None, exc: Exception
    ) -> None:
        try:
            await langfuse_service.get_langfuse_client().mark_span_failed(span_id, exc)
        except Exception:
            logger.exception("langfuse.stage_span_failure_mark_failed")

    async def generate(
        self,
        stage_id: UUID,
        user,
        db: AsyncSession,
        *,
        trace_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        stage = await self._load_stage(stage_id, db, lock=True)
        workspace = await self._load_workspace(stage.workspace_id, db)

        if stage.status not in ("draft", "stale"):
            raise StageStateError(f"Stage status {stage.status!r} is not generatable")

        await self._assert_dependencies_finalised(stage.type, workspace.id, db)

        if stage.type == "spec":
            try:
                assert_valid_problem_statement(workspace.problem_statement)
            except ProblemStatementValidationError as exc:
                raise SecurityError(exc.result.message or str(exc)) from exc

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

        # _cleanup_done starts False immediately after the commit so that any
        # exception — including a build_prompt() failure — enters the finally
        # cleanup path and refunds credits + resets the stage to draft.
        _cleanup_done = False
        span_id: str | None = None
        span_finished = False
        try:
            if trace_id:
                span_id = await self._start_langfuse_span(
                    trace_id=trace_id,
                    workspace=workspace,
                    user=user,
                    stage=stage,
                    action="generate",
                )

            system_prompt, user_prompt = await build_prompt(
                stage.type, workspace, db, redis
            )

            accumulated = ""
            content_generation_id: str | None = None
            try:
                adapter = get_llm(workspace.provider, workspace.model)
                if trace_id:
                    from services.llm.instrumented_adapter import InstrumentedAdapter

                    adapter = InstrumentedAdapter(
                        adapter,
                        span_id=span_id,
                        trace_id=trace_id,
                        provider=workspace.provider,
                        model=workspace.model,
                        stage_type=stage.type,
                        action="generate",
                    )
                async with asyncio.timeout(settings.llm_stream_timeout_seconds):
                    async for token in adapter.stream(
                        system_prompt, user_prompt, max_tokens=8192
                    ):
                        accumulated += token
                        yield token
                content_generation_id = getattr(adapter, "last_generation_id", None)
            except (ProviderError, TimeoutError) as exc:
                await credit_service.refund(db, deduction.id)
                stage.status = "draft"
                stage.updated_at = datetime.now(UTC)
                await db.commit()
                _cleanup_done = True
                if span_id:
                    await self._mark_langfuse_span_failed(span_id, exc)
                    span_finished = True
                if isinstance(exc, TimeoutError):
                    raise ProviderError(workspace.provider, exc) from exc
                raise exc

            accumulated = _strip_code_fence(accumulated)

            validation = validate(accumulated)
            if not validation.is_safe:
                await credit_service.refund(db, deduction.id)
                stage.status = "draft"
                stage.updated_at = datetime.now(UTC)
                await db.commit()
                _cleanup_done = True
                if span_id:
                    await self._mark_langfuse_span_failed(
                        span_id, SecurityError(validation.reason)
                    )
                    span_finished = True
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
            _cleanup_done = True
            if span_id:
                await self._end_langfuse_span(span_id)
                span_finished = True
            await self._invalidate_stage_cache(workspace.id, stage.type, redis)
            eval_task = asyncio.create_task(
                run_eval_background(
                    version_id,
                    stage.type,
                    accumulated,
                    spec_content,
                    workspace.provider,
                    JUDGE_MODELS[workspace.provider],
                    content_generation_id=content_generation_id,
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
        except Exception as exc:
            if span_id and not span_finished:
                await self._mark_langfuse_span_failed(span_id, exc)
            raise
        finally:
            if not _cleanup_done:
                if span_id and not span_finished:
                    await self._mark_langfuse_span_failed(
                        span_id,
                        RuntimeError("stage generation interrupted before completion"),
                    )
                    span_finished = True
                # Client disconnected before generation completed. The request-scoped
                # db session may be torn down, so open a fresh one for cleanup.
                from database import AsyncSessionLocal

                try:
                    async with AsyncSessionLocal() as cleanup_db:
                        result = await cleanup_db.execute(
                            select(Stage).where(Stage.id == stage_id)
                        )
                        stuck = result.scalar_one_or_none()
                        if stuck is not None and stuck.status == "in_progress":
                            await credit_service.refund(cleanup_db, deduction.id)
                            stuck.status = "draft"
                            stuck.updated_at = datetime.now(UTC)
                            await cleanup_db.commit()
                except Exception:
                    logger.exception(
                        "stage.disconnect_cleanup_error",
                        extra={"stage_id": str(stage_id)},
                    )

    async def refine(
        self,
        stage_id: UUID,
        request: RefineRequest,
        user,
        db: AsyncSession,
        *,
        trace_id: str | None = None,
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
            content[request.selection_start : request.selection_end]
            != request.selected_text
        ):
            raise RefineSelectionError("Selected text no longer matches the document")

        doc_len = len(content)
        selection_len = request.selection_end - request.selection_start
        large_selection = doc_len > 0 and (selection_len / doc_len) > 0.80

        system_prompt = (
            "You are SpecForge. Rewrite only the selected text per the instruction. "
            "Return ONLY the replacement text, nothing else.\n\n"
            f"{SECURITY_AND_PRIVACY_RULES}"
        )
        sanitized_instruction = sanitize_text(request.instruction)
        sanitized_selected_text = sanitize_text(request.selected_text)
        user_prompt = (
            f"Current document:\n"
            f"{wrap_untrusted_content('current_document', content)}\n\n"
            f"Selected text:\n"
            f"{wrap_untrusted_content('selected_text', sanitized_selected_text)}\n\n"
            f"Instruction:\n"
            f"{wrap_untrusted_content('instruction', sanitized_instruction)}\n\n"
            "Provide the replacement text only."
        )

        deduction = await credit_service.deduct(
            db, user.id, CREDIT_COSTS["refine"], "refine"
        )

        span_id: str | None = None
        span_finished = False
        try:
            if trace_id:
                span_id = await self._start_langfuse_span(
                    trace_id=trace_id,
                    workspace=workspace,
                    user=user,
                    stage=stage,
                    action="refine",
                )
            adapter = get_llm(workspace.provider, workspace.model)
            if trace_id:
                from services.llm.instrumented_adapter import InstrumentedAdapter

                adapter = InstrumentedAdapter(
                    adapter,
                    span_id=span_id,
                    trace_id=trace_id,
                    provider=workspace.provider,
                    model=workspace.model,
                    stage_type=stage.type,
                    action="refine",
                )
            replacement = await asyncio.wait_for(
                adapter.complete(system_prompt, user_prompt, max_tokens=4096),
                timeout=settings.llm_complete_timeout_seconds,
            )

            validation = validate(replacement)
            if not validation.is_safe:
                raise SecurityError(
                    f"Refine output failed validation: {validation.reason}"
                )
        except (ProviderError, SecurityError, TimeoutError) as exc:
            await credit_service.refund(db, deduction.id, user.id)
            if span_id:
                await self._mark_langfuse_span_failed(span_id, exc)
                span_finished = True
            if isinstance(exc, TimeoutError):
                raise ProviderError(workspace.provider, exc) from exc
            raise
        except Exception as exc:
            if span_id and not span_finished:
                await self._mark_langfuse_span_failed(span_id, exc)
            raise

        proposed = apply_diff(
            content,
            request.selection_start,
            request.selection_end,
            replacement,
        )
        diff = compute_diff(content, proposed)
        if span_id:
            await self._end_langfuse_span(span_id)

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

    async def _load_stage(
        self, stage_id: UUID, db: AsyncSession, *, lock: bool = False
    ) -> Stage:
        stmt = select(Stage).where(Stage.id == stage_id)
        if lock:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
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

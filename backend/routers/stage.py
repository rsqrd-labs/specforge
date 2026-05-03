from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from middleware.credit_check import require_credits
from models import EvalResult, Stage, StageVersion, User, Workspace
from schemas.stage import (
    AcceptDiffRequest,
    ContentEditRequest,
    DiffResponse,
    RefineRequest,
    RollbackRequest,
    StageResponse,
    StageVersionResponse,
)
from services.credit_service import InsufficientCreditsError, credit_service
from services.llm.base import ProviderError
from services.pipeline.stage_manager import (
    RateLimitError,
    SecurityError,
    StageDependencyError,
    stage_manager,
)
from services.security.sanitizer import sanitize_text

router = APIRouter(prefix="/stages", tags=["stages"])


async def _stream_stage(
    stage_id: UUID,
    user: User,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    try:
        async for token in stage_manager.generate(stage_id, user, db):
            if token.startswith('{"done"'):
                yield f"data: {token}\n\n"
            else:
                yield f"data: {json.dumps({'token': token})}\n\n"
    except StageDependencyError as exc:
        payload = json.dumps({"error": "dependency_not_finalised", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except RateLimitError as exc:
        payload = json.dumps(
            {"error": "rate_limit_exceeded", "retry_after": exc.retry_after}
        )
        yield f"data: {payload}\n\n"
    except SecurityError as exc:
        payload = json.dumps({"error": "security_check_failed", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except ProviderError as exc:
        payload = json.dumps({"error": "provider_error", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except Exception as exc:
        payload = json.dumps({"error": "internal_error", "detail": str(exc)})
        yield f"data: {payload}\n\n"


async def _load_stage(stage_id: UUID, db: AsyncSession, user_id: UUID) -> Stage:
    result = await db.execute(
        select(Stage)
        .join(Workspace, Stage.workspace_id == Workspace.id)
        .where(Stage.id == stage_id, Workspace.user_id == user_id)
    )
    stage = result.scalar_one_or_none()
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage not found")
    return stage


@router.get("/{stage_id}", response_model=StageResponse)
async def get_stage(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    stage = await _load_stage(stage_id, db, user.id)
    return StageResponse.model_validate(stage)


@router.post("/{stage_id}/generate")
async def generate_stage(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_credits(10)),
) -> StreamingResponse:
    await _load_stage(stage_id, db, user.id)
    return StreamingResponse(
        _stream_stage(stage_id, user, db), media_type="text/event-stream"
    )


@router.post("/{stage_id}/regenerate")
async def regenerate_stage(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_credits(10)),
) -> StreamingResponse:
    await _load_stage(stage_id, db, user.id)
    return StreamingResponse(
        _stream_stage(stage_id, user, db), media_type="text/event-stream"
    )


@router.post("/{stage_id}/refine", response_model=DiffResponse)
async def refine_stage(
    stage_id: UUID,
    request: RefineRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiffResponse:
    await _load_stage(stage_id, db, user.id)
    sanitized_request = request.model_copy(
        update={
            "instruction": sanitize_text(request.instruction),
            "selected_text": sanitize_text(request.selected_text),
        }
    )
    try:
        return await stage_manager.refine(stage_id, sanitized_request, user, db)
    except RateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limit_exceeded", "retry_after": exc.retry_after},
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except SecurityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "security_check_failed", "message": str(exc)},
        ) from exc


@router.post("/{stage_id}/accept-diff", response_model=StageResponse)
async def accept_diff(
    stage_id: UUID,
    body: AcceptDiffRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(stage_id, db, user.id)
    try:
        deduction = await credit_service.deduct(db, user.id, 3, "refine")
    except InsufficientCreditsError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "insufficient_credits", "required": 3},
        ) from exc

    try:
        stage = await stage_manager.handle_content_edit(
            stage_id, body.proposed_content, user, db
        )
    except Exception:
        await credit_service.refund(db, deduction.id, user.id)
        raise
    return StageResponse.model_validate(stage)


@router.post("/{stage_id}/reject-diff", status_code=status.HTTP_200_OK)
async def reject_diff(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await _load_stage(stage_id, db, user.id)
    return {"rejected": True}


@router.post("/{stage_id}/finalise", response_model=StageResponse)
async def finalise_stage(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(stage_id, db, user.id)
    try:
        stage = await stage_manager.finalise(stage_id, user, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return StageResponse.model_validate(stage)


@router.post("/{stage_id}/rollback", response_model=StageResponse)
async def rollback_stage(
    stage_id: UUID,
    body: RollbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(stage_id, db, user.id)
    stage = await stage_manager.rollback(stage_id, body.version_number, user, db)
    return StageResponse.model_validate(stage)


@router.post("/{stage_id}/acknowledge-gate", response_model=StageResponse)
async def acknowledge_gate(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    stage = await _load_stage(stage_id, db, user.id)
    stage.review_gate_acknowledged = True
    stage.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(stage)
    return StageResponse.model_validate(stage)


@router.get("/{stage_id}/versions", response_model=list[StageVersionResponse])
async def list_versions(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[StageVersionResponse]:
    await _load_stage(stage_id, db, user.id)
    result = await db.execute(
        select(StageVersion)
        .where(StageVersion.stage_id == stage_id)
        .order_by(desc(StageVersion.version))
    )
    return [StageVersionResponse.model_validate(v) for v in result.scalars()]


@router.get("/{stage_id}/eval")
async def get_eval(
    stage_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await _load_stage(stage_id, db, user.id)
    result = await db.execute(
        select(EvalResult)
        .join(StageVersion, EvalResult.stage_version_id == StageVersion.id)
        .where(StageVersion.stage_id == stage_id)
        .order_by(desc(EvalResult.created_at))
        .limit(1)
    )
    eval_result = result.scalar_one_or_none()
    if eval_result is None:
        raise HTTPException(status_code=404, detail="No eval result found")
    return {
        "id": str(eval_result.id),
        "stage_version_id": str(eval_result.stage_version_id),
        "stage_type": eval_result.stage_type,
        "overall_score": eval_result.overall_score,
        "completeness": eval_result.completeness,
        "clarity": eval_result.clarity,
        "coverage_percent": eval_result.coverage_percent,
        "uncovered_reqs": eval_result.uncovered_reqs,
        "tasks_without_ref": eval_result.tasks_without_ref,
        "flagged": eval_result.flagged,
        "created_at": eval_result.created_at.isoformat(),
    }


@router.patch("/{stage_id}/content", response_model=StageResponse)
async def edit_content(
    stage_id: UUID,
    body: ContentEditRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(stage_id, db, user.id)
    stage = await stage_manager.handle_content_edit(stage_id, body.content, user, db)
    return StageResponse.model_validate(stage)

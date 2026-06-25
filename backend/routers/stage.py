from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, get_redis
from middleware.auth import get_current_user
from middleware.credit_check import require_credits
from models import EvalResult, Stage, StageVersion, User, Workspace
from schemas.stage import (
    AcceptDiffRequest,
    ContentEditRequest,
    DiffResponse,
    GenerationEstimatesResponse,
    RefineRequest,
    RollbackRequest,
    StageResponse,
    StageVersionResponse,
)
from services.credit_service import InsufficientCreditsError
from services.evals.online_eval import (
    extract_deferred_reqs,
    validate_stage_findings,
)
from services.llm.base import ProviderError, ProviderTimeoutError
from services.llm.generation_estimates import read_generation_estimates
from services.pipeline.artifact_validator import MissingSectionError
from services.pipeline.critic import StageQualityGateError
from services.pipeline.stage_manager import (
    PreflightError,
    QualityGateBlockedError,
    RateLimitError,
    RefineSelectionError,
    SecurityError,
    StageDependencyError,
    StageStateError,
    stage_manager,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stages", tags=["stages"])


async def _stream_stage(
    stage_id: UUID,
    user: User,
    db: AsyncSession,
    trace_id: str,
    free: bool = False,
    action: str = "generate",
) -> AsyncGenerator[str, None]:
    try:
        async for token in stage_manager.generate(
            stage_id, user, db, trace_id=trace_id, free=free, action=action
        ):
            if (
                token.startswith('{"done"')
                or token.startswith('{"eval"')
                or token.startswith('{"quality_gate_failed"')
                or token.startswith('{"progress"')
                or token.startswith('{"stream_reset"')
            ):
                yield f"data: {token}\n\n"
            else:
                yield f"data: {json.dumps({'token': token})}\n\n"
    except StageQualityGateError as exc:
        # The quality_gate_failed event was already streamed to the client before
        # generate() raised; emit nothing further so the frontend does not also
        # see a misleading internal_error.  Credits were refunded and the stage
        # reset to draft inside generate().
        logger.info(
            "stage_quality_gate_failed",
            extra={
                "stage_id": str(stage_id),
                "stage": exc.stage_type,
                "finding_count": len(exc.findings),
            },
        )
    except MissingSectionError as exc:
        # T-248: same contract as the critic gate above — the quality_gate_failed
        # (kind=missing_sections) event was already streamed before generate()
        # raised, and credits were refunded + the stage reset to draft.
        logger.info(
            "stage_missing_sections",
            extra={
                "stage_id": str(stage_id),
                "stage": exc.stage_type,
                "missing_count": len(exc.missing),
            },
        )
    except StageDependencyError as exc:
        payload = json.dumps({"error": "dependency_not_finalised", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except StageStateError as exc:
        payload = json.dumps({"error": "stage_not_generatable", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except RateLimitError as exc:
        payload = json.dumps(
            {"error": "rate_limit_exceeded", "retry_after": exc.retry_after}
        )
        yield f"data: {payload}\n\n"
    except SecurityError as exc:
        payload = json.dumps({"error": "security_check_failed", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except PreflightError as exc:
        payload = json.dumps({"error": exc.code, "detail": exc.message})
        yield f"data: {payload}\n\n"
    except ProviderTimeoutError as exc:
        payload = json.dumps(
            {
                "error": "provider_timeout",
                "detail": str(exc),
                "timeout_seconds": exc.timeout_seconds,
            }
        )
        yield f"data: {payload}\n\n"
    except ProviderError as exc:
        payload = json.dumps({"error": "provider_error", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except InsufficientCreditsError:
        payload = json.dumps({"error": "insufficient_credits", "required": 10})
        yield f"data: {payload}\n\n"
    except Exception:
        logger.exception(
            "stage_stream_internal_error", extra={"stage_id": str(stage_id)}
        )
        payload = json.dumps({"error": "internal_error"})
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


@router.get("/generation-estimates", response_model=GenerationEstimatesResponse)
async def get_generation_estimates(
    redis: Redis = Depends(get_redis),
    _: User = Depends(get_current_user),
) -> GenerationEstimatesResponse:
    """Aggregate, data-backed generation-ETA bands (issue #21 Phase 2b).

    A pure Redis read of the rollup the worker cron precomputes — the heavy
    ledger query never runs on the request path. Authenticated and covered by the
    default per-user/IP read limits. Aggregate-only (durations + counts, no PII);
    a cache miss returns an empty list and the client falls back to its heuristic
    table. Declared before ``/{id}`` so the static path is not parsed as a UUID.
    """
    payload = await read_generation_estimates(redis)
    return GenerationEstimatesResponse.model_validate(payload)


@router.get("/{id}", response_model=StageResponse)
async def get_stage(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    stage = await _load_stage(id, db, user.id)
    return StageResponse.model_validate(stage)


@router.post("/{id}/generate")
async def generate_stage(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_credits(10)),
) -> StreamingResponse:
    await _load_stage(id, db, user.id)
    trace_id = str(uuid4())
    return StreamingResponse(
        _stream_stage(id, user, db, trace_id, action="generate"),
        media_type="text/event-stream",
    )


@router.post("/{id}/regenerate")
async def regenerate_stage(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_credits(10)),
) -> StreamingResponse:
    await _load_stage(id, db, user.id)
    trace_id = str(uuid4())
    return StreamingResponse(
        _stream_stage(id, user, db, trace_id, action="regenerate"),
        media_type="text/event-stream",
    )


async def _stream_harness_patch(
    stage_id: UUID,
    user: User,
    db: AsyncSession,
    uncovered_reqs: list[str],
    trace_id: str,
) -> AsyncGenerator[str, None]:
    try:
        async for token in stage_manager.generate_harness_patch(
            stage_id, user, db, uncovered_reqs, trace_id=trace_id
        ):
            if token.startswith('{"done"') or token.startswith('{"eval"'):
                yield f"data: {token}\n\n"
            else:
                yield f"data: {json.dumps({'token': token})}\n\n"
    except StageStateError as exc:
        payload = json.dumps({"error": "stage_not_generatable", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except RateLimitError as exc:
        payload = json.dumps(
            {"error": "rate_limit_exceeded", "retry_after": exc.retry_after}
        )
        yield f"data: {payload}\n\n"
    except ProviderTimeoutError as exc:
        payload = json.dumps(
            {
                "error": "provider_timeout",
                "detail": str(exc),
                "timeout_seconds": exc.timeout_seconds,
            }
        )
        yield f"data: {payload}\n\n"
    except ProviderError as exc:
        payload = json.dumps({"error": "provider_error", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except SecurityError as exc:
        payload = json.dumps({"error": "security_check_failed", "detail": str(exc)})
        yield f"data: {payload}\n\n"
    except InsufficientCreditsError:
        payload = json.dumps({"error": "insufficient_credits", "required": 10})
        yield f"data: {payload}\n\n"
    except Exception:
        logger.exception(
            "harness_patch_stream_error", extra={"stage_id": str(stage_id)}
        )
        yield f"data: {json.dumps({'error': 'internal_error'})}\n\n"


@router.post("/{id}/regenerate-gaps")
async def regenerate_stage_for_gaps(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Targeted paid patch for harness stages with coverage gaps to fill.

    Generates only the new test files needed for the listed requirements and merges
    them into the existing harness. Charges credits (see ``generate_harness_patch``)
    and is repeatable — gated on the user's balance, not a one-shot free flag.
    """
    stage = await _load_stage(id, db, user.id)
    if stage.type != "harness":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "not_harness_stage"},
        )

    result = await db.execute(
        select(EvalResult)
        .join(StageVersion, EvalResult.stage_version_id == StageVersion.id)
        .where(StageVersion.stage_id == stage.id)
        .order_by(desc(EvalResult.created_at))
        .limit(1)
    )
    latest_eval = result.scalar_one_or_none()

    # The patch covers two distinct sources, unioned (eval reqs first):
    #   1. LLM-derived uncovered_reqs on the latest harness eval, and
    #   2. requirement IDs the harness deterministically recorded as deferred
    #      under token budget (TestCategoryGap reqs=), parsed straight from the
    #      harness content — independent of the eval, so a harness with deferred
    #      coverage but an empty/missing eval still patches. extract_deferred_reqs
    #      filters out non-id tokens (e.g. property_based entity names) so the
    #      patch is never asked to invent tests for bogus "requirements".
    eval_uncovered: list[str] = list(
        (latest_eval.uncovered_reqs if latest_eval else None) or []
    )
    deferred_reqs = extract_deferred_reqs(stage.content or "")
    uncovered_reqs: list[str] = list(dict.fromkeys([*eval_uncovered, *deferred_reqs]))
    if not uncovered_reqs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_coverage_gaps"},
        )

    trace_id = str(uuid4())
    return StreamingResponse(
        _stream_harness_patch(stage.id, user, db, uncovered_reqs, trace_id),
        media_type="text/event-stream",
    )


@router.post("/{id}/refine", response_model=DiffResponse)
async def refine_stage(
    id: UUID,
    request: RefineRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(require_credits(3)),
) -> DiffResponse:
    # StageManager raw-matches selected_text before its prompt layer calls
    # sanitize_text(request.selected_text) and sanitize_text(request.instruction).
    await _load_stage(id, db, user.id)
    trace_id = str(uuid4())
    try:
        return await stage_manager.refine(id, request, user, db, trace_id=trace_id)
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
    except RefineSelectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "selection_mismatch", "message": str(exc)},
        ) from exc
    except PreflightError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": exc.code, "message": exc.message},
        ) from exc
    except InsufficientCreditsError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "insufficient_credits", "required": 3},
        ) from exc


@router.post("/{id}/accept-diff", response_model=StageResponse)
async def accept_diff(
    id: UUID,
    body: AcceptDiffRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(id, db, user.id)
    stage = await stage_manager.handle_content_edit(id, body.proposed_content, user, db)
    return StageResponse.model_validate(stage)


@router.post("/{id}/reject-diff", status_code=status.HTTP_200_OK)
async def reject_diff(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await _load_stage(id, db, user.id)
    return {"rejected": True}


@router.post("/{id}/finalise", response_model=StageResponse)
async def finalise_stage(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(id, db, user.id)
    try:
        stage = await stage_manager.finalise(id, user, db)
    except QualityGateBlockedError as exc:
        # Structured 409 the frontend renders directly: the gate kind plus a
        # derived recovery contract. Must precede the bare-ValueError catch
        # below, since QualityGateBlockedError subclasses ValueError.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "quality_gate_blocked",
                "kind": exc.kind,
                "message": exc.message,
                "recovery": exc.recovery,
            },
        ) from exc
    except ValueError as exc:
        # Non-gate finalise rejections (e.g. status != 'draft') stay 409-string.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return StageResponse.model_validate(stage)


@router.post("/{id}/acknowledge-stale", response_model=StageResponse)
async def acknowledge_stale_stage(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    """Keep a stale stage's content as-is, restoring it to finalised.

    Backs the "Keep" action on the staleness banner: re-affirms the existing
    finalised artifact without a regenerate. A non-stale stage is a 409.
    """
    await _load_stage(id, db, user.id)
    try:
        stage = await stage_manager.acknowledge_stale(id, user, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return StageResponse.model_validate(stage)


@router.post("/{id}/rollback", response_model=StageResponse)
async def rollback_stage(
    id: UUID,
    body: RollbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(id, db, user.id)
    stage = await stage_manager.rollback(id, body.version_number, user, db)
    return StageResponse.model_validate(stage)


@router.post("/{id}/acknowledge-gate", response_model=StageResponse)
async def acknowledge_gate(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    stage = await _load_stage(id, db, user.id)
    stage.review_gate_acknowledged = True
    stage.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(stage)
    return StageResponse.model_validate(stage)


@router.post("/{id}/override-quality-gate", response_model=StageResponse)
async def override_quality_gate(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(id, db, user.id)
    try:
        stage = await stage_manager.override_quality_gate(id, user, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return StageResponse.model_validate(stage)


@router.get("/{id}/versions", response_model=list[StageVersionResponse])
async def list_versions(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[StageVersionResponse]:
    await _load_stage(id, db, user.id)
    result = await db.execute(
        select(StageVersion)
        .where(StageVersion.stage_id == id)
        .order_by(desc(StageVersion.version))
    )
    return [StageVersionResponse.model_validate(v) for v in result.scalars()]


@router.get("/{id}/eval")
async def get_eval(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    stage = await _load_stage(id, db, user.id)
    result = await db.execute(
        select(EvalResult)
        .join(StageVersion, EvalResult.stage_version_id == StageVersion.id)
        .where(
            StageVersion.stage_id == id,
            StageVersion.version == stage.current_version,
        )
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
        # Requirement IDs whose harness test category was deferred under token
        # budget (TestCategoryGap). Non-blocking, but remediable by the free
        # harness patch — surfaced here so CoveragePanel can light the button
        # even when the LLM-derived uncovered_reqs is empty. Only harness content
        # carries these records; other stages yield an empty list.
        "deferred_reqs": extract_deferred_reqs(stage.content or ""),
        "tasks_without_ref": eval_result.tasks_without_ref,
        "flagged": eval_result.flagged,
        "created_at": eval_result.created_at.isoformat(),
    }


@router.post("/{id}/revalidate-tasks")
async def revalidate_tasks(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Re-run the structural task-reference validator on existing content.

    No LLM call; uses the deterministic parser against the current harness.
    Existing quality scores (overall_score, completeness, etc.) are preserved.
    """
    stage = await _load_stage(id, db, user.id)
    if stage.type != "tasks":
        raise HTTPException(status_code=400, detail="Stage is not a tasks stage")
    if not stage.content:
        raise HTTPException(status_code=400, detail="Tasks stage has no content yet")

    # Fetch harness stage for the same workspace
    harness_result = await db.execute(
        select(Stage).where(
            Stage.workspace_id == stage.workspace_id,
            Stage.type == "harness",
        )
    )
    harness_stage = harness_result.scalar_one_or_none()
    harness_content = harness_stage.content if harness_stage else ""

    # Same deterministic helper the generation flow uses inline — one source of
    # truth for task traceability, no LLM call (issue #27 Phase 1).
    tasks_without_ref, flagged = validate_stage_findings(
        "tasks", stage.content, harness_content or ""
    )

    # Fetch the existing eval for the current version to preserve quality scores
    eval_result_row = await db.execute(
        select(EvalResult)
        .join(StageVersion, EvalResult.stage_version_id == StageVersion.id)
        .where(
            StageVersion.stage_id == id,
            StageVersion.version == stage.current_version,
        )
        .order_by(desc(EvalResult.created_at))
        .limit(1)
    )
    eval_result = eval_result_row.scalar_one_or_none()

    if eval_result is not None:
        eval_result.tasks_without_ref = tasks_without_ref
        eval_result.flagged = flagged
    else:
        # No prior eval — create a minimal one with structural results only
        version_result = await db.execute(
            select(StageVersion)
            .where(
                StageVersion.stage_id == id,
                StageVersion.version == stage.current_version,
            )
            .limit(1)
        )
        version = version_result.scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="Stage version not found")
        eval_result = EvalResult(
            stage_version_id=version.id,
            stage_type="tasks",
            overall_score=None,
            completeness=None,
            clarity=None,
            coverage_percent=None,
            uncovered_reqs=None,
            tasks_without_ref=tasks_without_ref,
            flagged=flagged,
        )
        db.add(eval_result)

    await db.commit()
    await db.refresh(eval_result)

    return {
        "id": str(eval_result.id),
        "stage_version_id": str(eval_result.stage_version_id),
        "stage_type": eval_result.stage_type,
        "overall_score": eval_result.overall_score,
        "completeness": eval_result.completeness,
        "clarity": eval_result.clarity,
        "coverage_percent": eval_result.coverage_percent,
        "uncovered_reqs": eval_result.uncovered_reqs,
        # Tasks content carries no TestCategoryGap records, so this is empty here;
        # included only to keep the eval response shape uniform across endpoints.
        "deferred_reqs": extract_deferred_reqs(stage.content or ""),
        "tasks_without_ref": eval_result.tasks_without_ref,
        "flagged": eval_result.flagged,
        "created_at": eval_result.created_at.isoformat(),
    }


@router.patch("/{id}/content", response_model=StageResponse)
async def edit_content(
    id: UUID,
    body: ContentEditRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StageResponse:
    await _load_stage(id, db, user.id)
    stage = await stage_manager.handle_content_edit(id, body.content, user, db)
    return StageResponse.model_validate(stage)

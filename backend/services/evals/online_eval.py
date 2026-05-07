from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models import EvalResult
from services import langfuse_service
from services.llm.gateway import get_llm
from services.llm.provider_config import JUDGE_MODELS

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = (
    "You are a strict software specification evaluator. "
    "Respond ONLY with valid JSON matching the requested schema. No other text."
)

_STAGE_PROMPTS: dict[str, str] = {
    "spec": (
        "Evaluate this software specification.\n"
        'Return JSON: {{"overall_score": int (0-100), "completeness": int (0-100), '
        '"clarity": int (0-100)}}\n\n'
        "Content:\n{content}"
    ),
    "plan": (
        "Evaluate this implementation plan against the specification.\n"
        'Return JSON: {{"overall_score": int (0-100), "completeness": int (0-100), '
        '"clarity": int (0-100)}}\n\n'
        "Spec:\n{spec_content}\n\nPlan:\n{content}"
    ),
    "harness": (
        "Evaluate this test harness against the specification.\n"
        'Return JSON: {{"overall_score": int (0-100), "completeness": int (0-100), '
        '"clarity": int (0-100), "coverage_percent": int (0-100), '
        '"uncovered_reqs": list[str]}}\n\n'
        "Spec:\n{spec_content}\n\nHarness:\n{content}"
    ),
    "tasks": (
        "Evaluate this task list against the test harness.\n"
        'Return JSON: {{"overall_score": int (0-100), "completeness": int (0-100), '
        '"clarity": int (0-100), "tasks_without_ref": list[{{"task": str, '
        '"reason": str}}]}}\n\n'
        "Spec:\n{spec_content}\n\nTasks:\n{content}"
    ),
}


async def run_eval(
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    db: AsyncSession,
    provider: str = "anthropic",
    judge_model: str | None = None,
    content_generation_id: str | None = None,
) -> EvalResult | None:
    try:
        resolved_judge_model = judge_model or JUDGE_MODELS[provider]
        judge = get_llm(provider, resolved_judge_model)
        user_prompt = _STAGE_PROMPTS[stage_type].format(
            content=content, spec_content=spec_content
        )
        raw = await asyncio.wait_for(
            judge.complete(_JUDGE_SYSTEM, user_prompt, max_tokens=1024),
            timeout=settings.llm_complete_timeout_seconds,
        )
    except Exception:
        logger.exception(
            "eval judge call failed for stage_version_id=%s", stage_version_id
        )
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(
            "eval judge returned non-JSON for stage_version_id=%s: %r",
            stage_version_id,
            raw[:200],
        )
        return None

    coverage_percent: int | None = data.get("coverage_percent")
    uncovered_reqs: list[str] | None = data.get("uncovered_reqs")
    tasks_without_ref: list | None = data.get("tasks_without_ref")

    flagged = False
    if (
        stage_type == "harness"
        and coverage_percent is not None
        and coverage_percent < 80
    ):
        flagged = True
    if stage_type == "tasks" and tasks_without_ref:
        flagged = True

    eval_result = EvalResult(
        stage_version_id=stage_version_id,
        stage_type=stage_type,
        overall_score=data.get("overall_score"),
        completeness=data.get("completeness"),
        clarity=data.get("clarity"),
        coverage_percent=coverage_percent,
        uncovered_reqs=uncovered_reqs,
        tasks_without_ref=tasks_without_ref,
        flagged=flagged,
    )
    db.add(eval_result)
    await db.commit()
    await db.refresh(eval_result)
    if content_generation_id and eval_result.overall_score is not None:
        try:
            await langfuse_service.get_langfuse_client().score_generation(
                generation_id=content_generation_id,
                name="overall",
                value=float(eval_result.overall_score),
            )
        except Exception:
            logger.exception(
                "eval score link failed for stage_version_id=%s",
                stage_version_id,
            )
    return eval_result


async def run_eval_background(
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str,
    judge_model: str,
    content_generation_id: str | None = None,
) -> EvalResult | None:
    async with AsyncSessionLocal() as db:
        return await run_eval(
            stage_version_id,
            stage_type,
            content,
            spec_content,
            db,
            provider,
            judge_model,
            content_generation_id,
        )

"""Stage-eval dispatch facade.

V1 uses the online judge in online_eval.py for all stages, but keeping this
dispatch table makes the stage coverage explicit and preserves the older module
boundary expected by tooling.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models import EvalResult
from services.evals.online_eval import run_eval

EVALUATORS = {
    "spec": "spec_eval",
    "plan": "plan_eval",
    "harness": "harness_eval",
    "tasks": "tasks_eval",
}


async def dispatch_eval(
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    db: AsyncSession,
    provider: str = "anthropic",
    judge_model: str | None = None,
) -> EvalResult | None:
    if stage_type not in EVALUATORS:
        raise ValueError(f"Unknown stage type: {stage_type!r}")
    return await run_eval(
        stage_version_id,
        stage_type,
        content,
        spec_content,
        db,
        provider,
        judge_model,
    )

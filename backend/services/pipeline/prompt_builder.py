from __future__ import annotations

import json
import logging

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import prompts.harness as harness_prompts
import prompts.plan as plan_prompts
import prompts.spec as spec_prompts
import prompts.tasks as tasks_prompts
from config import settings
from models import Stage, Workspace
from services.pipeline.stage_summary_service import summarize_stage_content

logger = logging.getLogger(__name__)

_STAGE_CACHE_PREFIX = "stage:"
_STAGE_CACHE_TTL = 3600  # 1 hour
_MAX_UPSTREAM_CHARS = 50_000

_PROMPT_MODULES = {
    "spec": spec_prompts,
    "plan": plan_prompts,
    "harness": harness_prompts,
    "tasks": tasks_prompts,
}

_DEPENDENCIES: dict[str, list[str]] = {
    "spec": [],
    "plan": ["spec"],
    "harness": ["spec", "plan"],
    "tasks": ["spec", "plan", "harness"],
}


async def build_prompt(
    stage_type: str,
    workspace: Workspace,
    db: AsyncSession,
    redis_client: Redis | None = None,
) -> tuple[str, str]:
    module = _PROMPT_MODULES[stage_type]
    dep_keys = _DEPENDENCIES[stage_type]

    deps: dict[str, str] = {"problem_statement": workspace.problem_statement}

    # Phase 14: thread persisted Spec Clarification Q&A into the spec
    # prompt so regenerates honour the user's earlier answers without a
    # second round of questioning. JSON-encoded to preserve the existing
    # dict[str, str] dependency contract; spec.build_user_prompt decodes.
    if stage_type == "spec" and getattr(workspace, "clarification_qa", None):
        deps["clarification_qa"] = json.dumps(workspace.clarification_qa)

    if dep_keys:
        redis = redis_client or Redis.from_url(
            settings.redis_url, decode_responses=True
        )
        for dep_type in dep_keys:
            content = await _fetch_stage_content(dep_type, workspace.id, db, redis)
            if len(content) > _MAX_UPSTREAM_CHARS:
                logger.warning(
                    "upstream_content_summarized",
                    extra={"stage": dep_type, "original_len": len(content)},
                )
                content = summarize_stage_content(dep_type, content).content
                if len(content) > _MAX_UPSTREAM_CHARS:
                    logger.warning(
                        "upstream_summary_truncated",
                        extra={"stage": dep_type, "summary_len": len(content)},
                    )
                    content = content[:_MAX_UPSTREAM_CHARS]
            deps[dep_type] = content

    return await module.get_system_prompt(), module.build_user_prompt(deps)


async def _fetch_stage_content(
    stage_type: str,
    workspace_id,
    db: AsyncSession,
    redis: Redis,
) -> str:
    cache_key = f"{_STAGE_CACHE_PREFIX}{workspace_id}:{stage_type}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(Stage).where(
            Stage.workspace_id == workspace_id,
            Stage.type == stage_type,
        )
    )
    stage = result.scalar_one_or_none()
    content = (stage.content or "") if stage else ""
    await redis.set(cache_key, content, ex=_STAGE_CACHE_TTL)
    return content

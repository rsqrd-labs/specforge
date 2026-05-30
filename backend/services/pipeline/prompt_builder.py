from __future__ import annotations

import json
import logging
import re

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import prompts.harness as harness_prompts
import prompts.plan as plan_prompts
import prompts.spec as spec_prompts
import prompts.tasks as tasks_prompts
from config import settings
from database import get_shared_redis
from models import Stage, Workspace
from services.observability import PIPELINE_UPSTREAM_SECTION_SKIPPED
from services.pipeline.stage_summary_service import summarize_stage_content

logger = logging.getLogger(__name__)

_STAGE_CACHE_PREFIX = "stage:"
_STAGE_CACHE_TTL = 3600  # 1 hour
_MAX_UPSTREAM_CHARS = 200_000  # T-246: raised from 50K (models accept 200K+ ctx)

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

# Sections that must be kept verbatim downstream — these are the IDs and
# contracts the downstream stage names by reference.  Order matters: kept
# sections are concatenated in the order listed.
_STAGE_KEEP_SECTIONS: dict[str, list[str]] = {
    "spec": [
        "## Functional Requirements",
        "## Non-Functional Requirements",
        "## Security, Privacy, and Abuse Expectations",
        "## Conceptual Domain Model",
        "## Acceptance Criteria",
    ],
    "plan": [
        "## Requirement Traceability Matrix",
        "## API Design",
        "## Security Architecture",
        "## Data Model and Persistence",
    ],
    "harness": [
        "## Requirement-to-Test Matrix",
        "## File Tree",
    ],
}


def _split_by_h2(content: str) -> list[tuple[str, str]]:
    """Split a markdown document on `## ` h2 headings.  Preserves order.

    Any preamble before the first h2 heading is returned as a leading
    section with an empty heading so its content (which may carry
    requirement IDs or API contracts) is summarized rather than silently
    dropped — silent upstream loss is the exact F-7.1 failure mode.
    """
    segments = re.split(r"(?m)^(## .+)$", content)
    parts: list[tuple[str, str]] = []
    # segments alternates: [preamble, heading1, body1, heading2, body2, ...]
    preamble = segments[0]
    if preamble.strip():
        parts.append(("", preamble))
    i = 1
    while i < len(segments):
        heading = segments[i].strip()
        body = segments[i + 1] if i + 1 < len(segments) else ""
        parts.append((heading, body))
        i += 2
    return parts


def _section_aware_injection(stage_type: str, content: str) -> str:
    """Keep critical sections verbatim, summarize narrative sections.

    Used only when content exceeds _MAX_UPSTREAM_CHARS even after the 200K
    bump.  For each section in _STAGE_KEEP_SECTIONS[stage_type] that is
    skipped (not preserved verbatim due to remaining budget), the metric
    `pipeline_upstream_section_skipped_total{stage, section}` is
    incremented so dashboards can observe the quality regression.
    """
    keep = _STAGE_KEEP_SECTIONS.get(stage_type, [])
    sections = _split_by_h2(content)
    preserved: list[str] = []
    summarized: list[str] = []
    budget_remaining = _MAX_UPSTREAM_CHARS
    for heading, body in sections:
        full = f"{heading}\n{body}"
        if heading in keep and len(full) <= budget_remaining:
            preserved.append(full)
            budget_remaining -= len(full)
        elif heading in keep:
            # Critical section but no budget — skip and record.  We drop
            # rather than summarize so the metric fires a fail-loud alert
            # instead of masking the loss with a lossy RTM summary.
            PIPELINE_UPSTREAM_SECTION_SKIPPED.labels(
                stage=stage_type, section=heading
            ).inc()
        else:
            summarized.append(full)
    summary = summarize_stage_content(stage_type, "\n".join(summarized)).content
    return "\n".join(preserved + [summary])[:_MAX_UPSTREAM_CHARS]


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
        redis = redis_client or get_shared_redis()  # H-1 — T-177
        for dep_type in dep_keys:
            content = await _fetch_stage_content(dep_type, workspace.id, db, redis)
            if len(content) > _MAX_UPSTREAM_CHARS:
                logger.warning(
                    "upstream_content_section_aware_injection",
                    extra={"stage": dep_type, "original_len": len(content)},
                )
                content = _section_aware_injection(dep_type, content)
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

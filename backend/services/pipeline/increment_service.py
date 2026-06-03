"""Delta-aware increment generation (Phase 21 — T-279).

A finalised workspace evolves as a versioned **timeline** — v1 → Increment 1 →
Increment 2 → … — that absorbs new features as **deltas** rather than freezing at
the first export or churning the whole pipeline on a full re-run (spec §4.14.7).

The load-bearing property is a **stable, content-derived ``task_ref``** (spec
Assumption 23): every task the baseline already carries keeps the *same* ref
across the increment, so the incremental GitHub sync (T-280) updates that task's
existing Issue instead of opening a duplicate; only genuinely new tasks get new
refs and therefore new Issues. That key is decided once in Phase A
(``task_parser.compute_task_ref``) and *consumed* here — never re-invented.

How a delta is produced (additive path — the MVP):

1. The finalised stages are the **baseline**: immutable context the prompt is
   explicitly told never to rewrite, renumber, or re-emit. (Treating the baseline
   as mutable is exactly the failure that regresses an increment into a full,
   churny regeneration.)
2. The model returns **only the new tasks** required for the feature request, in
   the same ``### T-NNN: <title>`` shape as TASKS.md.
3. Output is reconciled against the baseline: any task whose content-derived
   ``task_ref`` already exists is dropped (defence-in-depth against a model that
   re-emits an existing task), and the genuinely new tasks are renumbered to
   continue after the highest baseline ``T-NNN``.
4. The new tasks are **appended** to the Tasks stage as a new ``StageVersion`` —
   the workspace's TASKS.md grows; the baseline versions are pinned on the
   ``Increment`` row (``baseline_version_ids``) so the delta is reproducible.

Behaviour-changing increments — compute the blast radius, mark affected items
``stale``, and re-run harness/critic *only* on the affected areas — are the
phase-two cut (spec "v2 fast-follow"). They are scoped here but gated behind
``settings.increment_blast_radius_enabled`` (default off); the additive path is
the only one that ships in the MVP.

Generation is credit-aware and refund-safe, consistent with the rest of the
pipeline: credits are deducted up front and refunded on any failure, and the
increment row is left in a retryable ``draft`` state. An increment is only worth
charging less than a full generation because it is genuinely scoped — token usage
is measured and logged so that claim stays honest.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_shared_redis
from models import Increment, Stage, StageVersion, Workspace
from prompts.base import SECURITY_AND_PRIVACY_RULES, wrap_untrusted_content
from services.credit_service import credit_service
from services.integrations.task_parser import (
    AGENT_LABELS,
    compute_task_ref,
    parse_tasks,
)
from services.llm.base import ProviderError, ProviderTimeoutError
from services.llm.gateway import get_llm
from services.llm.output_budget import output_budget_for_operation
from services.llm.routing import LLMRoutingError, resolve_llm_route
from services.pipeline.diff_engine import markdown_fences_balanced
from services.security.output_validator import validate
from services.security.prompt_guard import scan
from services.security.sanitizer import sanitize_text

logger = logging.getLogger(__name__)

# A scoped delta is cheaper than a full 10-credit generation but never free — the
# increment still runs a real model call. Held here (not in ``CREDIT_COSTS``) so
# the increment surface owns its own pricing without touching the shared table;
# passed to ``credit_service.deduct`` with ``reason="increment"``.
INCREMENT_CREDIT_COST = 5

# Increment generation rides the Tasks routing tiers — it produces TASKS-shaped
# output and shares the ``tasks.generate`` operation/budget.
_INCREMENT_OPERATION = "tasks.generate"
_INCREMENT_TIERS = ("mini", "small")

# Cap the persisted increment title so an oversized feature request cannot bloat
# the row; the full request still drives generation.
_TITLE_MAX_LEN = 120

# Matches a ``### T-NNN: <title>`` heading so the highest baseline number can be
# found and new tasks renumbered to continue after it.
_TASK_HEADING = re.compile(r"^###\s+T-(\d+):", re.MULTILINE)


class IncrementError(Exception):
    """Base class for increment-generation failures."""


class IncrementBaselineError(IncrementError):
    """The workspace is not in a state that can be incremented (e.g. a stage is
    not finalised, so there is no immutable baseline to delta against)."""


class IncrementGenerationError(IncrementError):
    """The model returned no usable delta (no new tasks after reconciliation)."""


class IncrementModeNotSupportedError(IncrementError):
    """A behaviour-changing increment was requested while the blast-radius path
    is still gated off (MVP ships additive only)."""


@dataclass(frozen=True)
class IncrementTask:
    """A single new task introduced by an increment.

    ``human_ref`` is the renumbered ``T-NNN`` heading (continues after the
    baseline); ``task_ref`` is the stable, content-derived matching key used by
    sync to find/create the Issue. The two bodies mirror :class:`ParsedTask`.
    """

    human_ref: str
    task_ref: str
    title: str
    body_md: str
    agent_body_md: str
    raw_body: str = ""
    labels: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IncrementResult:
    """Outcome of a delta generation."""

    increment_id: UUID
    sequence: int
    title: str
    new_tasks: list[IncrementTask]
    pinned_task_refs: list[str]
    tasks_version_id: UUID


_STAGE_ORDER = ("spec", "plan", "harness", "tasks")


class IncrementService:
    """Generates a delta increment on a finalised workspace baseline (T-279)."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis = redis_client

    async def _redis_conn(self) -> Redis:
        if self._redis is None:
            self._redis = get_shared_redis()
        return self._redis

    async def generate_increment(
        self,
        workspace_id: UUID,
        feature_request: str,
        user,
        db: AsyncSession,
        *,
        mode: str = "additive",
    ) -> IncrementResult:
        """Generate an additive increment from ``feature_request``.

        The baseline (all four finalised stages) is fixed context; the output is a
        **diff** — only the new tasks — appended to TASKS.md as a new version with
        stable, content-derived ``task_ref``s. Credits are deducted up front and
        refunded on any failure.
        """
        if mode not in ("additive", "behaviour_changing"):
            raise ValueError(f"Unknown increment mode: {mode!r}")
        if mode == "behaviour_changing" and not settings.increment_blast_radius_enabled:
            # Phase-two cut: blast-radius analysis is scoped but not shipped.
            raise IncrementModeNotSupportedError(
                "Behaviour-changing increments (blast-radius analysis) are not yet "
                "available. The MVP ships the additive path only."
            )

        scan_result = scan(feature_request)
        if not scan_result.is_safe:
            raise IncrementError(
                f"Feature request flagged: {scan_result.matched_pattern}"
            )

        workspace = await self._load_workspace(workspace_id, db)
        stages = await self._load_finalised_stages(db, workspace_id)
        baseline_version_ids = await self._baseline_version_ids(db, stages)

        baseline_tasks_md = stages["tasks"].content or ""
        baseline_parsed = parse_tasks(baseline_tasks_md)
        pinned_refs = [compute_task_ref(t.title) for t in baseline_parsed]
        pinned_ref_set = set(pinned_refs)
        baseline_max = _highest_task_number(baseline_tasks_md)

        route = self._resolve_route(workspace)
        sequence = await self._next_sequence(db, workspace_id)
        title = _derive_title(feature_request)

        increment = Increment(
            workspace_id=workspace_id,
            sequence=sequence,
            title=title,
            status="generating",
            baseline_version_ids=baseline_version_ids,
        )
        db.add(increment)
        await db.flush()
        increment_id = increment.id

        # Credit up front; deduct() raises InsufficientCreditsError before any LLM
        # spend if the balance is short. Refunded on every downstream failure.
        deduction = await credit_service.deduct(
            db, user.id, INCREMENT_CREDIT_COST, "increment"
        )

        system_prompt = _system_prompt()
        user_prompt = _user_prompt(stages, feature_request, baseline_max)

        try:
            adapter = get_llm(route.provider, route.model)
            completion = await asyncio.wait_for(
                adapter.complete(
                    system_prompt,
                    user_prompt,
                    max_tokens=output_budget_for_operation(route.operation),
                ),
                timeout=settings.llm_complete_timeout_seconds,
            )

            validation = validate(completion)
            if not validation.is_safe:
                raise IncrementError(
                    f"Increment output failed validation: {validation.reason}"
                )

            new_tasks = _reconcile_delta(completion, pinned_ref_set, baseline_max)
            if not new_tasks:
                raise IncrementGenerationError(
                    "The increment produced no new tasks for this feature request."
                )

            new_tasks_md = _grow_tasks_markdown(baseline_tasks_md, new_tasks)
            if not markdown_fences_balanced(new_tasks_md):
                raise IncrementError(
                    "Increment output would leave Markdown code fences unbalanced."
                )

            version_id = await self._append_tasks_version(
                db, stages["tasks"], new_tasks_md
            )
            increment.status = "ready"
            increment.updated_at = datetime.now(UTC)
            await db.commit()
        except (
            ProviderError,
            ProviderTimeoutError,
            IncrementError,
            asyncio.TimeoutError,
        ) as exc:
            await self._refund_and_mark_draft(db, increment_id, deduction, user)
            if isinstance(exc, asyncio.TimeoutError):
                raise ProviderError(route.provider, exc) from exc
            raise

        await credit_service.invalidate(user.id)  # post-commit — H-2 pattern (T-219)
        await self._invalidate_tasks_cache(workspace_id)

        _log_token_usage(
            increment_id=increment_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            completion=completion,
            new_task_count=len(new_tasks),
        )

        return IncrementResult(
            increment_id=increment_id,
            sequence=sequence,
            title=title,
            new_tasks=new_tasks,
            pinned_task_refs=pinned_refs,
            tasks_version_id=version_id,
        )

    # ------------------------------------------------------------------ helpers

    def _resolve_route(self, workspace: Workspace):
        requested_tier, fallback_tier = _INCREMENT_TIERS
        try:
            return resolve_llm_route(
                operation=_INCREMENT_OPERATION,
                preferred_provider=workspace.provider,
                requested_tier=requested_tier,
                fallback_tier=fallback_tier,
                latency_class="interactive",
            )
        except LLMRoutingError as exc:
            raise IncrementError(
                "The selected provider/model is not available for increment "
                "generation."
            ) from exc

    async def _load_workspace(self, workspace_id: UUID, db: AsyncSession) -> Workspace:
        workspace = (
            await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        if workspace is None:
            raise IncrementBaselineError("Workspace not found")
        return workspace

    async def _load_finalised_stages(
        self, db: AsyncSession, workspace_id: UUID
    ) -> dict[str, Stage]:
        result = await db.execute(
            select(Stage).where(Stage.workspace_id == workspace_id)
        )
        stages = {s.type: s for s in result.scalars()}
        for stage_type in _STAGE_ORDER:
            stage = stages.get(stage_type)
            if stage is None or stage.status != "finalised":
                raise IncrementBaselineError(
                    f"Stage {stage_type!r} is not finalised — a workspace must be "
                    "finalised before it can be incremented."
                )
        return stages

    async def _baseline_version_ids(
        self, db: AsyncSession, stages: dict[str, Stage]
    ) -> list[str]:
        """Pin the immutable StageVersion ids that form the delta's baseline."""
        ids: list[str] = []
        for stage_type in _STAGE_ORDER:
            stage = stages[stage_type]
            version_id = (
                await db.execute(
                    select(StageVersion.id).where(
                        StageVersion.stage_id == stage.id,
                        StageVersion.version == stage.current_version,
                    )
                )
            ).scalar_one_or_none()
            if version_id is not None:
                ids.append(str(version_id))
        return ids

    async def _next_sequence(self, db: AsyncSession, workspace_id: UUID) -> int:
        highest = (
            await db.execute(
                select(func.max(Increment.sequence)).where(
                    Increment.workspace_id == workspace_id
                )
            )
        ).scalar_one_or_none()
        return (highest or 0) + 1

    async def _append_tasks_version(
        self, db: AsyncSession, tasks_stage: Stage, new_content: str
    ) -> UUID:
        """Grow TASKS.md by one additive version.

        The stage stays ``finalised`` — the grown document is still a complete,
        valid TASKS.md — so existing exports/syncs are not staled by the
        increment (drift staling is reserved for an explicit re-finalise, T-273).
        """
        tasks_stage.content = new_content
        tasks_stage.current_version += 1
        tasks_stage.updated_at = datetime.now(UTC)
        version = StageVersion(
            stage_id=tasks_stage.id,
            version=tasks_stage.current_version,
            content=new_content,
            created_by="ai",
        )
        db.add(version)
        await db.flush()
        return version.id

    async def _refund_and_mark_draft(
        self, db: AsyncSession, increment_id: UUID, deduction, user
    ) -> None:
        """Refund the increment credit and leave the row in a retryable state.

        The credit is returned exactly once; the increment is reset to ``draft``
        so the user can retry without an orphaned ``generating`` row stuck in the
        timeline. Committed here so the refund survives even if the caller's
        request fails afterwards.
        """
        try:
            await credit_service.refund(db, deduction.id, user.id)
            increment = (
                await db.execute(select(Increment).where(Increment.id == increment_id))
            ).scalar_one_or_none()
            if increment is not None:
                increment.status = "draft"
                increment.updated_at = datetime.now(UTC)
            await db.commit()
            await credit_service.invalidate(user.id)
        except Exception:  # pragma: no cover - defensive cleanup
            logger.exception(
                "increment.refund_cleanup_failed increment_id=%s", increment_id
            )

    async def _invalidate_tasks_cache(self, workspace_id: UUID) -> None:
        try:
            redis = await self._redis_conn()
            await redis.delete(f"stage:{workspace_id}:tasks")
        except RedisError:  # cache eviction is best-effort
            logger.warning(
                "increment.tasks_cache_evict_failed workspace_id=%s", workspace_id
            )


# ---------------------------------------------------------------------------
# Pure helpers (deterministic, unit-testable without a DB)
# ---------------------------------------------------------------------------


def _highest_task_number(tasks_md: str) -> int:
    """Highest ``T-NNN`` number present in TASKS.md, or 0 when none."""
    numbers = [int(m.group(1)) for m in _TASK_HEADING.finditer(tasks_md)]
    return max(numbers, default=0)


def _reconcile_delta(
    completion: str, pinned_ref_set: set[str], baseline_max: int
) -> list[IncrementTask]:
    """Turn raw model output into the genuinely-new tasks.

    Drops any task whose content-derived ``task_ref`` already exists in the
    baseline (a model that re-emits existing work must never duplicate an Issue),
    de-duplicates within the delta itself, and renumbers the survivors to continue
    after the highest baseline ``T-NNN``.
    """
    parsed = parse_tasks(completion)
    seen: set[str] = set()
    new_tasks: list[IncrementTask] = []
    next_number = baseline_max
    for task in parsed:
        ref = compute_task_ref(task.title)
        if ref in pinned_ref_set or ref in seen:
            continue
        seen.add(ref)
        next_number += 1
        human_ref = f"T-{next_number:03d}"
        new_tasks.append(
            IncrementTask(
                human_ref=human_ref,
                task_ref=ref,
                title=task.title,
                body_md=task.body_md,
                agent_body_md=task.agent_body_md,
                raw_body=task.raw_body,
                labels=task.labels or AGENT_LABELS,
            )
        )
    return new_tasks


def _render_task_section(task: IncrementTask) -> str:
    heading = f"### {task.human_ref}: {task.title}"
    body = task.raw_body.strip()
    return f"{heading}\n\n{body}" if body else heading


def _grow_tasks_markdown(baseline_tasks_md: str, new_tasks: list[IncrementTask]) -> str:
    """Append the new task sections to TASKS.md, existing content pinned verbatim.

    The new sections are re-rendered under their renumbered headings with each
    task's source body preserved verbatim, so the appended block matches the
    source document's shape.
    """
    appended = "\n\n".join(_render_task_section(task) for task in new_tasks)
    base = baseline_tasks_md.rstrip()
    if base:
        return f"{base}\n\n{appended}\n"
    return f"{appended}\n"


def _system_prompt() -> str:
    return (
        "You are SpecForge generating an INCREMENT: a versioned delta on a "
        "finalised workspace baseline.\n\n"
        "The baseline below — SPEC.md, PLAN.md, the test harness, and TASKS.md — "
        "is IMMUTABLE context. You MUST NOT rewrite it, renumber its tasks, "
        "restate its tasks, or reproduce any task it already contains. Treating "
        "the baseline as mutable regresses this into a full regeneration, which is "
        "wrong.\n\n"
        "Output ONLY the NEW tasks required to deliver the requested feature, as a "
        "delta to append to TASKS.md. Use the exact same shape as the baseline "
        "tasks:\n"
        "  ### T-NNN: <concise imperative title>\n"
        "  <the same labelled subsections the baseline tasks use>\n\n"
        "Rules:\n"
        "- Number the new tasks consecutively, continuing AFTER the highest "
        "existing T-NNN.\n"
        "- Reuse the baseline's exact terminology, entity names, requirement IDs, "
        "and test-path conventions. Do not invent synonyms for defined terms.\n"
        "- Reference existing baseline tasks by their T-NNN where a new task "
        "depends on them, but never restate or modify them.\n"
        "- Each new task must be independently implementable and testable.\n"
        "- Emit nothing but the new ### T-NNN task sections — no preamble, no "
        "recap of existing work, no closing commentary.\n\n"
        f"{SECURITY_AND_PRIVACY_RULES}"
    )


def _user_prompt(
    stages: dict[str, Stage], feature_request: str, baseline_max: int
) -> str:
    sanitized_request = sanitize_text(feature_request)
    spec = stages["spec"].content or ""
    plan = stages["plan"].content or ""
    harness = stages["harness"].content or ""
    tasks = stages["tasks"].content or ""
    next_number = baseline_max + 1
    return (
        "Baseline workspace (immutable — do not modify or re-emit):\n\n"
        f"{wrap_untrusted_content('baseline_spec', spec)}\n\n"
        f"{wrap_untrusted_content('baseline_plan', plan)}\n\n"
        f"{wrap_untrusted_content('baseline_harness', harness)}\n\n"
        f"{wrap_untrusted_content('baseline_tasks', tasks)}\n\n"
        "Feature request to absorb as an additive increment:\n"
        f"{wrap_untrusted_content('feature_request', sanitized_request)}\n\n"
        f"Append the new tasks only. Start numbering at T-{next_number:03d}. "
        "Do not repeat any task already present in the baseline TASKS."
    )


def _derive_title(feature_request: str) -> str:
    """A short, single-line, sanitised title for the increment row."""
    cleaned = sanitize_text(feature_request)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > _TITLE_MAX_LEN:
        cleaned = cleaned[: _TITLE_MAX_LEN - 1].rstrip() + "…"
    return cleaned or "Untitled increment"


def _approx_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) — enough to keep the "an increment
    is only cheaper if genuinely scoped" claim measurable in the logs."""
    return max(1, len(text) // 4)


def _log_token_usage(
    *,
    increment_id: UUID,
    system_prompt: str,
    user_prompt: str,
    completion: str,
    new_task_count: int,
) -> None:
    prompt_tokens = _approx_tokens(system_prompt) + _approx_tokens(user_prompt)
    completion_tokens = _approx_tokens(completion)
    logger.info(
        "increment.generated increment_id=%s new_tasks=%d "
        "approx_prompt_tokens=%d approx_completion_tokens=%d",
        increment_id,
        new_task_count,
        prompt_tokens,
        completion_tokens,
    )


increment_service = IncrementService()

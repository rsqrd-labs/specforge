"""Deferred (batched) eval scoring on the durable worker (Phase 3, issue #26).

Replaces the cosmetic ``batch`` flag with real provider Message Batches for the
one truly non-interactive judge call — ``eval.score`` — to claim the 50% batch
discount. The PR-check judge and the critic deliberately stay on the inline path
(both gate something a human or persistence is waiting on; a multi-hour batch
turnaround would be wrong there).

Lifecycle, all on the arq worker:

  producer  → create ``LLMBatchJob`` (pending) + enqueue ``llm_batch_submit``
  submit    → create the provider batch, persist ``provider_batch_id`` (submitted)
  sweep cron→ re-enqueue stuck pending rows; enqueue ``llm_batch_collect`` per
              submitted row
  collect   → poll; once ended, parse + persist the EvalResult, record the
              (half-price) cost event, delete the row

The provider bills a batch whether or not its results are collected, so the
batch id is checkpointed the instant the batch is created. Jobs are idempotent
on the row id; collect is a no-op once the row is gone. A parse miss or an
errored/expired result falls back to **one** synchronous inline score (never a
re-batch — a batch round trip can take hours). Only Anthropic has a wired batch
adapter today; every other provider (and the queue/flag being off) cleanly uses
the synchronous in-process path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select

from database import AsyncSessionLocal
from models import LLMBatchJob
from services.evals.online_eval import (
    build_eval_request,
    persist_eval_from_raw,
    run_eval,
)
from services.llm.base import BatchRequest, BatchUnsupportedError
from services.llm.cost_ledger import LLMCostContext, persist_cost_event
from services.llm.cost_registry import get_provider_capabilities, model_tier
from services.llm.gateway import get_llm
from services.llm.usage import estimate_cost_usd, normalize_provider_usage
from services.observability import (
    LLM_BATCH_COLLECTED_TOTAL,
    LLM_BATCH_SUBMITTED_TOTAL,
    record_llm_cost_event,
)
from services.queue import enqueue

logger = structlog.get_logger(__name__)

_OPERATION = "eval.score"
_PROMPT_VERSION = "eval-v2"
_PRODUCT_SURFACE = "eval"
# Providers with a wired Message Batches adapter. Others fall back to sync even
# though the catalog flags supports_batch=True (no verified SDK batch surface).
_REAL_BATCH_PROVIDERS = frozenset({"anthropic"})
# Safety cap: a batch that never reaches "ended" by this age is scored inline
# instead of churning the poll cron forever (Anthropic batches end ≤ 24h).
_BATCH_MAX_AGE = timedelta(hours=26)
# Bound per-sweep fan-out so a backlog cannot flood the worker in one tick.
_SWEEP_LIMIT = 200


def provider_supports_real_batch(provider: str) -> bool:
    """True if *provider* has a wired Message Batches adapter we can submit to."""
    if provider not in _REAL_BATCH_PROVIDERS:
        return False
    try:
        return bool(get_provider_capabilities(provider)["supports_batch"])
    except Exception:
        return False


async def enqueue_eval_batch(
    *,
    stage_version_id: UUID,
    stage_type: str,
    content: str,
    spec_content: str,
    provider: str,
    judge_model: str,
    content_generation_id: str | None,
    harness_content: str | None,
    workspace_id: UUID | None,
) -> UUID:
    """Checkpoint a pending eval batch row and enqueue its submit job.

    Returns the new row id. Raises if the row cannot be committed (the caller
    then falls back to a synchronous in-process eval so scoring still happens).
    An enqueue failure *after* the row is committed is swallowed — the sweep cron
    re-enqueues pending rows, so we never double-score by also falling back.
    """
    system, user_prompt, max_tokens = build_eval_request(
        stage_type, content, spec_content, provider
    )
    context = {
        "stage_version_id": str(stage_version_id),
        "stage_type": stage_type,
        "content": content,
        "spec_content": spec_content,
        "harness_content": harness_content,
        "content_generation_id": content_generation_id,
        "provider": provider,
        "judge_model": judge_model,
    }
    async with AsyncSessionLocal() as db:
        row = LLMBatchJob(
            status="pending",
            operation=_OPERATION,
            provider=provider,
            model=judge_model,
            model_tier=_model_tier_or_unknown(provider, judge_model),
            prompt_version=_PROMPT_VERSION,
            custom_id=f"eval-{stage_version_id}",
            request_system=system,
            request_user=user_prompt,
            max_tokens=max_tokens,
            context=context,
            workspace_id=workspace_id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        row_id = row.id

    try:
        await enqueue("llm_batch_submit", str(row_id), job_id=str(row_id))
    except Exception:
        # Queue blip: the row is durably pending, so the sweep cron re-enqueues
        # it. Do not raise — re-raising would make the caller also run a
        # synchronous eval, double-scoring the same artifact.
        logger.warning("llm_batch.enqueue_failed", batch_job_id=str(row_id))
    return row_id


async def run_submit(ctx: dict[str, Any], batch_job_id: str) -> None:
    """Create the provider batch for a pending row and checkpoint its id."""
    async with AsyncSessionLocal() as db:
        row = await db.get(LLMBatchJob, UUID(batch_job_id))
        if row is None or row.provider_batch_id is not None:
            # Already collected (row gone) or already submitted (idempotent).
            return
        adapter = get_llm(row.provider, row.model)
        request = BatchRequest(
            custom_id=row.custom_id,
            system=row.request_system,
            user=row.request_user,
            max_tokens=row.max_tokens,
        )
        # submit_batch creates the (billed) batch; persist its id immediately so
        # a crash after this point never loses a paid-for batch.
        provider_batch_id = await adapter.submit_batch([request])
        row.provider_batch_id = provider_batch_id
        row.status = "submitted"
        await db.commit()
    LLM_BATCH_SUBMITTED_TOTAL.labels(operation=_OPERATION, provider=row.provider).inc()
    logger.info(
        "llm_batch.submitted",
        batch_job_id=batch_job_id,
        provider_batch_id=provider_batch_id,
    )


async def run_collect(ctx: dict[str, Any], batch_job_id: str) -> None:
    """Poll a submitted batch; once ended, persist the result and drop the row."""
    async with AsyncSessionLocal() as db:
        row = await db.get(LLMBatchJob, UUID(batch_job_id))
        if row is None or row.status != "submitted" or not row.provider_batch_id:
            return  # already collected, or not yet submitted
        adapter = get_llm(row.provider, row.model)
        status = await adapter.poll_batch(row.provider_batch_id)
        if status != "ended":
            if _row_age(row) > _BATCH_MAX_AGE:
                logger.warning(
                    "llm_batch.stale_scoring_inline",
                    batch_job_id=batch_job_id,
                    last_status=status,
                )
                await _fallback_score(db, row)
                await db.delete(row)
                await db.commit()
                LLM_BATCH_COLLECTED_TOTAL.labels(
                    operation=_OPERATION, provider=row.provider, outcome="fallback"
                ).inc()
            else:
                row.attempts += 1
                await db.commit()  # re-checked on the next sweep tick
            return

        results = await adapter.fetch_batch_results(row.provider_batch_id)
        item = results.get(row.custom_id)
        outcome = await _finish_from_item(db, row, item)
        await db.delete(row)
        await db.commit()
    LLM_BATCH_COLLECTED_TOTAL.labels(
        operation=_OPERATION, provider=row.provider, outcome=outcome
    ).inc()
    logger.info("llm_batch.collected", batch_job_id=batch_job_id, outcome=outcome)


async def sweep(ctx: dict[str, Any]) -> None:
    """Cron: recover stuck pending rows and advance every submitted row.

    Plain cron (not the retry/dead-letter contract): a transient blip is
    recovered on the next tick, so it must never surface as a worker error.
    """
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(LLMBatchJob)
                        .where(LLMBatchJob.status.in_(("pending", "submitted")))
                        .order_by(LLMBatchJob.created_at)
                        .limit(_SWEEP_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
        for row in rows:
            job = "llm_batch_submit" if row.status == "pending" else "llm_batch_collect"
            try:
                await enqueue(job, str(row.id), job_id=str(row.id))
            except Exception:  # pragma: no cover — next tick retries
                logger.warning("llm_batch.sweep_enqueue_failed", job=job)
    except Exception:  # pragma: no cover — best-effort; next tick retries
        logger.exception("llm_batch.sweep_failed")


async def _finish_from_item(db: Any, row: LLMBatchJob, item: Any) -> str:
    """Persist the EvalResult from a batch item, recording the half-price cost.

    Falls back to one synchronous inline score when the item errored/expired or
    its text did not parse — never re-batches.
    """
    if item is not None and item.status == "succeeded" and item.text:
        await _record_batch_cost_event(row, item.usage)
        result = await persist_eval_from_raw(
            db,
            item.text,
            stage_version_id=UUID(row.context["stage_version_id"]),
            stage_type=row.context["stage_type"],
            content=row.context["content"],
            harness_content=row.context.get("harness_content"),
            content_generation_id=row.context.get("content_generation_id"),
        )
        if result is not None:
            return "succeeded"
    # Errored / expired / unparseable → one synchronous inline score.
    await _fallback_score(db, row)
    return "fallback"


async def _fallback_score(db: Any, row: LLMBatchJob) -> None:
    """Score this eval synchronously (full price, batch=False) as a last resort."""
    try:
        await run_eval(
            UUID(row.context["stage_version_id"]),
            row.context["stage_type"],
            row.context["content"],
            row.context["spec_content"],
            db,
            row.context["provider"],
            row.context["judge_model"],
            content_generation_id=row.context.get("content_generation_id"),
            harness_content=row.context.get("harness_content"),
        )
    except Exception:  # pragma: no cover — eval is best-effort, never fatal
        logger.exception("llm_batch.fallback_score_failed", batch_job_id=str(row.id))


async def _record_batch_cost_event(row: LLMBatchJob, raw_usage: dict | None) -> None:
    """Record the cost ledger + Prometheus event for a collected batch call.

    The batch path never goes through ``InstrumentedAdapter`` (it calls neither
    ``complete`` nor ``stream``), so the cost event is recorded here with the
    provider-reported usage and ``batch=True`` (the 50% discount applied in
    ``estimate_cost_usd``).
    """
    usage = normalize_provider_usage(row.provider, raw_usage)
    try:
        estimated_cost = estimate_cost_usd(row.provider, row.model, usage, batch=True)
    except Exception:
        estimated_cost = None
    metadata: dict[str, Any] = {
        "operation": _OPERATION,
        "provider": row.provider,
        "model": row.model,
        "model_tier": row.model_tier or "unknown",
        "prompt_version": row.prompt_version,
        "stage_type": _PRODUCT_SURFACE,
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "usage_estimation_method": usage.usage_estimation_method,
        "estimated_cost_usd": (
            float(estimated_cost) if estimated_cost is not None else None
        ),
        "cache_hit": False,
        "batch": True,
        "cross_provider_fallback": False,
    }
    metadata.update(
        LLMCostContext(
            workspace_id=row.workspace_id,
            product_surface=_PRODUCT_SURFACE,
        ).as_metadata()
    )
    try:
        record_llm_cost_event(metadata)
    except Exception:  # pragma: no cover — telemetry must never break collection
        logger.warning("llm_batch.cost_metric_failed", exc_info=True)
    # persist_cost_event is itself fully exception-swallowed and flag-gated.
    await persist_cost_event(metadata)


def _row_age(row: LLMBatchJob) -> timedelta:
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created


def _model_tier_or_unknown(provider: str, model: str) -> str:
    try:
        return model_tier(provider, model)
    except Exception:
        return "unknown"


# Suppress "unused" warnings for BatchUnsupportedError re-exported for callers
# that want to catch it without importing the adapter base directly.
__all__ = [
    "BatchUnsupportedError",
    "enqueue_eval_batch",
    "provider_supports_real_batch",
    "run_collect",
    "run_submit",
    "sweep",
]

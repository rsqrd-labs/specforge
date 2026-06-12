"""LLM cost ledger — Phase 0 of issue #26.

Persists one ``llm_cost_events`` row per provider call so spend can be rolled
up per workspace / stage / storyboard / increment and per operation / provider
/ model / outcome.

Two hard rules:

* **Never break a generation.** Every public coroutine here opens its own
  session and swallows all exceptions — a ledger failure must be invisible to
  the caller. Writes are awaited at a post-stream point (the user already has
  their tokens), so "fire-and-forget" here means "best-effort, non-fatal", not
  a detached task.
* **Never double-count reasoning.** ``reasoning_tokens`` is an observability
  breakout already inside ``output_tokens``; it is stored, never costed.

``LLMCostContext`` is the single opaque object that carries the product-surface
"who/why" (FK ids, credit reason, surface label) from a call site down to the
instrumentation layer, so the adapter signature does not grow a field per
domain concept.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import structlog

from config import settings

logger = structlog.get_logger(__name__)

# Hard ceiling on a single ledger DB round-trip. The persist/update run at a
# post-stream point and a slow (not refused) DB must never stall stream
# teardown — a breach is swallowed like any other ledger failure. asyncio's
# TimeoutError is an Exception subclass, so the existing handlers catch it; a
# watchdog CancelledError (BaseException) still propagates, as it must.
_LEDGER_DB_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class LLMCostContext:
    """Product-surface attribution for a single LLM call.

    All fields optional: a background judge call has no stage, a storyboard
    call has no increment, etc. Merged into the cost event by the
    instrumentation layer.
    """

    workspace_id: str | UUID | None = None
    stage_id: str | UUID | None = None
    storyboard_id: str | UUID | None = None
    increment_id: str | UUID | None = None
    credit_reason: str | None = None
    product_surface: str | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


# Columns on llm_cost_events that we accept from a metadata dict. Anything else
# in the dict (e.g. provider_usage_raw, which is not a column) is ignored.
_EVENT_FIELDS = frozenset(
    {
        "generation_id",
        "operation",
        "provider",
        "model",
        "model_tier",
        "prompt_version",
        "stage_type",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "usage_estimation_method",
        "estimated_cost_usd",
        "latency_ms",
        "finish_reason",
        "stopped_by_limit",
        "cache_hit",
        "batch",
        "cross_provider_fallback",
        "retry_count",
        "repair_count",
        "quality_outcome",
        "credit_reason",
        "product_surface",
        "workspace_id",
        "stage_id",
        "storyboard_id",
        "increment_id",
    }
)
_UUID_FIELDS = frozenset({"workspace_id", "stage_id", "storyboard_id", "increment_id"})


async def persist_cost_event(metadata: Mapping[str, Any]) -> None:
    """Insert one cost-ledger row from a cost-metadata mapping.

    Best-effort: gated by ``llm_cost_ledger_enabled`` and swallows every error
    so a ledger write can never surface to (or slow a hard failure into) the
    generation path.
    """
    if not settings.llm_cost_ledger_enabled:
        return
    try:
        from database import AsyncSessionLocal  # noqa: PLC0415
        from models import LLMCostEvent  # noqa: PLC0415

        row_kwargs = _row_kwargs_from_metadata(metadata)
        if not row_kwargs.get("provider") or not row_kwargs.get("model"):
            # provider/model are NOT NULL; without them there is nothing useful
            # to record. Skip rather than raise.
            return

        async def _write() -> None:
            async with AsyncSessionLocal() as db:
                db.add(LLMCostEvent(**row_kwargs))
                await db.commit()

        await asyncio.wait_for(_write(), timeout=_LEDGER_DB_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("llm_cost_ledger.persist_failed", exc_info=True)


async def update_cost_event_quality_outcome(
    generation_id: str | None,
    quality_outcome: str,
) -> None:
    """Set ``quality_outcome`` on the row(s) for *generation_id*.

    Called from the stage manager after the post-generation gates (artifact
    validator + critic) resolve, reusing the Langfuse generation id already
    threaded for eval-score linking. Best-effort; swallows all errors.
    """
    if not settings.llm_cost_ledger_enabled or not generation_id:
        return
    try:
        from sqlalchemy import update  # noqa: PLC0415

        from database import AsyncSessionLocal  # noqa: PLC0415
        from models import LLMCostEvent  # noqa: PLC0415

        async def _update() -> None:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(LLMCostEvent)
                    .where(LLMCostEvent.generation_id == generation_id)
                    .values(quality_outcome=quality_outcome)
                )
                await db.commit()

        await asyncio.wait_for(_update(), timeout=_LEDGER_DB_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("llm_cost_ledger.quality_update_failed", exc_info=True)


# Columns the rollup helper is allowed to GROUP BY (allowlist guards against
# SQL-injection via a caller-supplied dimension name).
_ROLLUP_DIMENSIONS = frozenset(
    {
        "operation",
        "provider",
        "model",
        "model_tier",
        "stage_type",
        "product_surface",
        "quality_outcome",
    }
)


async def cost_rollup(
    db: Any,
    *,
    group_by: str,
    since: Any | None = None,
    workspace_id: str | UUID | None = None,
) -> list[dict[str, Any]]:
    """Aggregate cost/tokens/calls grouped by one ledger dimension.

    Returns rows of ``{dimension, calls, input_tokens, cached_input_tokens,
    output_tokens, reasoning_tokens, estimated_cost_usd}`` ordered by spend
    descending. Read-only; the caller supplies the session.
    """
    if group_by not in _ROLLUP_DIMENSIONS:
        raise ValueError(f"Unsupported rollup dimension: {group_by!r}")

    from sqlalchemy import func, select  # noqa: PLC0415

    from models import LLMCostEvent  # noqa: PLC0415

    dimension = getattr(LLMCostEvent, group_by)
    stmt = (
        select(
            dimension.label("dimension"),
            func.count().label("calls"),
            func.coalesce(func.sum(LLMCostEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LLMCostEvent.cached_input_tokens), 0).label(
                "cached_input_tokens"
            ),
            func.coalesce(func.sum(LLMCostEvent.output_tokens), 0).label(
                "output_tokens"
            ),
            func.coalesce(func.sum(LLMCostEvent.reasoning_tokens), 0).label(
                "reasoning_tokens"
            ),
            func.coalesce(func.sum(LLMCostEvent.estimated_cost_usd), 0).label(
                "estimated_cost_usd"
            ),
        )
        .group_by(dimension)
        .order_by(func.coalesce(func.sum(LLMCostEvent.estimated_cost_usd), 0).desc())
    )
    if since is not None:
        stmt = stmt.where(LLMCostEvent.created_at >= since)
    if workspace_id is not None:
        coerced = _coerce_uuid(workspace_id)
        if coerced is not None:
            stmt = stmt.where(LLMCostEvent.workspace_id == coerced)

    result = await db.execute(stmt)
    return [
        {
            "dimension": row.dimension,
            "calls": int(row.calls),
            "input_tokens": int(row.input_tokens),
            "cached_input_tokens": int(row.cached_input_tokens),
            "output_tokens": int(row.output_tokens),
            "reasoning_tokens": int(row.reasoning_tokens),
            "estimated_cost_usd": float(row.estimated_cost_usd or 0),
        }
        for row in result
    ]


def _row_kwargs_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for field in _EVENT_FIELDS:
        if field not in metadata:
            continue
        value = metadata[field]
        if value is None:
            continue
        if field in _UUID_FIELDS:
            coerced = _coerce_uuid(value)
            if coerced is not None:
                row[field] = coerced
        elif field == "estimated_cost_usd":
            coerced_cost = _coerce_decimal(value)
            if coerced_cost is not None:
                row[field] = coerced_cost
        else:
            row[field] = value
    return row


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    with contextlib.suppress(ValueError, TypeError, AttributeError):
        return UUID(str(value))
    return None


def _coerce_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    with contextlib.suppress(InvalidOperation, ValueError, TypeError):
        return Decimal(str(value))
    return None

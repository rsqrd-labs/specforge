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


async def output_token_percentiles(
    db: Any,
    *,
    since: Any | None = None,
    operations: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Output-token distribution per (operation, provider) — the Phase-4
    evidence source for right-sizing budgets (issue #26).

    Returns one row per (operation, provider) with the sample count, the
    p50/p90/p95/max of ``output_tokens``, the p50/p95 of ``reasoning_tokens``
    (observability only — reasoning is already inside output_tokens and is
    never re-added to a budget), and the ``truncation_rate`` (fraction of calls
    that hit ``stopped_by_limit``). Read-only; the caller supplies the session.

    Only rows with a non-null ``output_tokens`` and a non-null ``operation``
    contribute, so estimate-only or unattributed calls do not pollute the
    distribution. ``truncation_rate`` is computed over those same rows.
    """
    from sqlalchemy import Float, cast, func, select  # noqa: PLC0415

    from models import LLMCostEvent  # noqa: PLC0415

    def _pct(level: float, column: Any) -> Any:
        # percentile_cont(level) WITHIN GROUP (ORDER BY column) — interpolated
        # percentile, the right tool for a continuous token count.
        return func.percentile_cont(level).within_group(column.asc())

    output_col = LLMCostEvent.output_tokens
    reasoning_col = LLMCostEvent.reasoning_tokens
    stmt = (
        select(
            LLMCostEvent.operation.label("operation"),
            LLMCostEvent.provider.label("provider"),
            func.count().label("samples"),
            _pct(0.50, output_col).label("p50_output_tokens"),
            _pct(0.90, output_col).label("p90_output_tokens"),
            _pct(0.95, output_col).label("p95_output_tokens"),
            func.max(output_col).label("max_output_tokens"),
            _pct(0.50, reasoning_col).label("p50_reasoning_tokens"),
            _pct(0.95, reasoning_col).label("p95_reasoning_tokens"),
            func.avg(cast(LLMCostEvent.stopped_by_limit, Float)).label(
                "truncation_rate"
            ),
        )
        .where(output_col.isnot(None))
        .where(LLMCostEvent.operation.isnot(None))
        .group_by(LLMCostEvent.operation, LLMCostEvent.provider)
        .order_by(LLMCostEvent.operation, LLMCostEvent.provider)
    )
    if since is not None:
        stmt = stmt.where(LLMCostEvent.created_at >= since)
    if operations:
        stmt = stmt.where(LLMCostEvent.operation.in_(operations))

    result = await db.execute(stmt)

    def _int(value: Any) -> int | None:
        return int(value) if value is not None else None

    return [
        {
            "operation": row.operation,
            "provider": row.provider,
            "samples": int(row.samples),
            "p50_output_tokens": _int(row.p50_output_tokens),
            "p90_output_tokens": _int(row.p90_output_tokens),
            "p95_output_tokens": _int(row.p95_output_tokens),
            "max_output_tokens": _int(row.max_output_tokens),
            "p50_reasoning_tokens": _int(row.p50_reasoning_tokens),
            "p95_reasoning_tokens": _int(row.p95_reasoning_tokens),
            "truncation_rate": (
                float(row.truncation_rate) if row.truncation_rate is not None else None
            ),
        }
        for row in result
    ]


async def generation_latency_percentiles(
    db: Any,
    *,
    since: Any | None = None,
    operations: list[str] | None = None,
) -> list[dict[str, Any]]:
    """End-to-end latency distribution per (operation, provider, stage_type) — the
    data source for the issue-#21 honest-ETA endpoint (Phase 2b).

    Returns one row per (operation, provider, stage_type) with the sample count
    and the p50/p90 of ``latency_ms``. ``latency_ms`` on a streamed generation
    row is the **full provider stream duration** (the instrumented adapter starts
    its timer before the stream and records in the ``finally`` after the last
    token), so it is the dominant term of user-perceived generation time.

    Aggregate-only — durations and counts, no per-user data and no PII. Read-only;
    the caller supplies the session. Only rows that represent a *live, interactive*
    provider call contribute:

    * ``latency_ms`` non-null and strictly positive (drops estimate-only rows),
    * ``cache_hit`` false (a cache replay is near-instant and unrepresentative),
    * ``batch`` false (batch jobs run for minutes-to-hours, off the request path),
    * ``operation``/``stage_type`` non-null (need both to key the estimate).

    p50/p90 are percentile-robust, so the rare watchdog-timeout tail (a hung
    stream recorded at ~the hard cap) does not distort them.
    """
    from sqlalchemy import func, select  # noqa: PLC0415

    from models import LLMCostEvent  # noqa: PLC0415

    def _pct(level: float, column: Any) -> Any:
        return func.percentile_cont(level).within_group(column.asc())

    latency_col = LLMCostEvent.latency_ms
    stmt = (
        select(
            LLMCostEvent.operation.label("operation"),
            LLMCostEvent.provider.label("provider"),
            LLMCostEvent.stage_type.label("stage_type"),
            func.count().label("samples"),
            _pct(0.50, latency_col).label("p50_latency_ms"),
            _pct(0.90, latency_col).label("p90_latency_ms"),
        )
        .where(latency_col.isnot(None))
        .where(latency_col > 0)
        .where(LLMCostEvent.cache_hit.is_(False))
        .where(LLMCostEvent.batch.is_(False))
        .where(LLMCostEvent.operation.isnot(None))
        .where(LLMCostEvent.stage_type.isnot(None))
        .group_by(
            LLMCostEvent.operation,
            LLMCostEvent.provider,
            LLMCostEvent.stage_type,
        )
        .order_by(
            LLMCostEvent.operation,
            LLMCostEvent.provider,
            LLMCostEvent.stage_type,
        )
    )
    if since is not None:
        stmt = stmt.where(LLMCostEvent.created_at >= since)
    if operations:
        stmt = stmt.where(LLMCostEvent.operation.in_(operations))

    result = await db.execute(stmt)

    def _int(value: Any) -> int | None:
        return int(value) if value is not None else None

    return [
        {
            "operation": row.operation,
            "provider": row.provider,
            "stage_type": row.stage_type,
            "samples": int(row.samples),
            "p50_latency_ms": _int(row.p50_latency_ms),
            "p90_latency_ms": _int(row.p90_latency_ms),
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

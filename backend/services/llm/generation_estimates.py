"""Honest generation-ETA aggregation — issue #21 Phase 2b.

A cheap periodic worker cron rolls ``llm_cost_events.latency_ms`` up into
aggregate p50/p90 *durations* per ``(provider, stage, operation)`` and caches the
result in Redis; the read-only ``GET /stages/generation-estimates`` endpoint
serves that cache without ever running the heavy query on the request path.

The output speaks the **frontend's** vocabulary, not the ledger's: the ledger
records an internal operation string (``"spec.generate"``, ``"refine.focused"``,
…) plus a ``stage_type`` column, and this module normalises those into the same
``(stage, operation)`` key space the client's heuristic table (Phase 2a) uses,
so the seam is a single dict lookup with an exact-match key and a clean
heuristic fallback. The mapping lives **here only** — the client never parses a
ledger string.

Security: aggregate-only. Every served field is a duration or a count derived
from ``generation_latency_percentiles`` (which already excludes anything but the
operation/provider/stage/latency dimensions). No user, workspace, prompt, or
output ever reaches this payload.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from config import settings
from services.llm.cost_ledger import (
    platform_generation_latency_percentiles as generation_latency_percentiles,
)

logger = structlog.get_logger(__name__)

# Redis key holding the cached rollup payload. Versioned so a shape change is a
# new key (an old reader never mis-parses a new blob, and vice versa).
CACHE_KEY = "generation_estimates:v2"

# The four pipeline stages, used both to recover a stage from a ledger operation
# prefix and to validate the stage_type column.
_STAGE_TYPES = ("spec", "plan", "harness", "tasks")

# Providers the response schema accepts. A ledger row for any other provider is
# dropped in compute so a stray value can never reach (and 500) the schema's
# Literal validation — the served payload only ever carries known providers.
# The operation tokens the client looks up. These mirror the canonical grouping
# the Phase-2a `estimateEta` already collapses its five activity operations into,
# so a live hit and a heuristic fallback share one key space.
LOOKUP_OPERATIONS = ("generate", "focused-patch", "regenerate-gaps")

# Sane band for a served estimate, in seconds. Anything outside it (clock skew, a
# stray sub-second row, a hung-stream tail that survived the percentile) is
# dropped so the client falls back to the heuristic rather than show a nonsense
# duration. The upper bound matches the stream hard cap.
_MIN_ESTIMATE_SECONDS = 2
_MAX_ESTIMATE_SECONDS = 3600


def _normalise_operation(operation: str, stage_type: str) -> tuple[str, str] | None:
    """Map a ledger ``(operation, stage_type)`` to a client ``(stage, lookup_op)``.

    Returns ``None`` for any operation we do not serve a live estimate for (e.g.
    ``regenerate.full``, ``critic.review``, ``eval.score``) — the client keeps the
    heuristic baseline for those, which is the intended robustness contract.
    """
    for stage in _STAGE_TYPES:
        if operation == f"{stage}.generate":
            # A fresh full-stage generation. The client canonicalises both
            # `generate` and `regenerate`/`quality-gate-regenerate` to this key.
            return (stage, "generate")
    if operation == "refine.focused" and stage_type in _STAGE_TYPES:
        return (stage_type, "focused-patch")
    return None


def _build_estimate(
    *,
    stage: str,
    lookup_op: str,
    p50_ms: int,
    p90_ms: int,
    samples: int,
    tail_seconds: int,
) -> dict[str, Any] | None:
    """Convert one aggregated ledger row into a served estimate, or ``None`` if
    it fails the sane-band guard.

    ms→seconds with the post-stream pipeline tail added so the served band
    reflects perceived wall-clock (stream + validator + critic + persist), not
    stream duration alone.
    """
    p50 = round(p50_ms / 1000) + tail_seconds
    p90 = round(p90_ms / 1000) + tail_seconds
    # Percentiles guarantee p90 >= p50; the equal tail preserves it. Clamp
    # defensively so a degenerate (p90 < p50) row can never be served.
    p90 = max(p90, p50)
    if not (_MIN_ESTIMATE_SECONDS <= p50 <= p90 <= _MAX_ESTIMATE_SECONDS):
        return None
    return {
        "stage": stage,
        "operation": lookup_op,
        "p50": p50,
        "p90": p90,
        "n": samples,
    }


async def compute_generation_estimates(
    db: Any,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Roll the latency ledger up into the served estimate list.

    One row per ``(provider, stage, operation)`` we have confident data for:
    ``{provider, stage, operation, p50, p90, n}`` (durations in seconds). Rows
    below the minimum sample count, outside the sane band, or for an operation we
    do not serve are dropped — the client falls back to the heuristic for them.
    """
    now = now or datetime.now(UTC)
    since = now - timedelta(days=max(1, settings.generation_estimates_window_days))
    min_samples = max(1, settings.generation_estimates_min_samples)
    tail = max(0, settings.generation_estimates_pipeline_tail_seconds)

    rows = await generation_latency_percentiles(db, since=since)

    estimates: list[dict[str, Any]] = []
    for row in rows:
        samples = int(row.get("samples") or 0)
        if samples < min_samples:
            continue
        p50_ms = row.get("p50_latency_ms")
        p90_ms = row.get("p90_latency_ms")
        operation = row.get("operation")
        stage_type = row.get("stage_type")
        if p50_ms is None or p90_ms is None or not operation:
            continue
        mapped = _normalise_operation(str(operation), str(stage_type or ""))
        if mapped is None:
            continue
        stage, lookup_op = mapped
        estimate = _build_estimate(
            stage=stage,
            lookup_op=lookup_op,
            p50_ms=int(p50_ms),
            p90_ms=int(p90_ms),
            samples=samples,
            tail_seconds=tail,
        )
        if estimate is not None:
            estimates.append(estimate)

    # Stable order so the cached payload is deterministic for a given input.
    estimates.sort(key=lambda e: (e["stage"], e["operation"]))
    return estimates


async def refresh_generation_estimates_cache(redis: Any, db: Any) -> int:
    """Recompute the rollup and write it to Redis. Returns the row count.

    No-op (and clears nothing) when the feature is disabled — an existing key is
    left to expire on its own TTL. Called from the worker cron.
    """
    if not settings.generation_estimates_enabled:
        return 0
    estimates = await compute_generation_estimates(db)
    payload = {
        "estimates": estimates,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    ttl = max(1, settings.generation_estimates_cache_ttl_seconds)
    await redis.set(CACHE_KEY, json.dumps(payload), ex=ttl)
    return len(estimates)


def _empty_payload() -> dict[str, Any]:
    return {"estimates": [], "generated_at": None}


async def read_generation_estimates(redis: Any) -> dict[str, Any]:
    """Read the cached rollup for the endpoint. Pure Redis read — never queries.

    Returns ``{"estimates": [...], "generated_at": iso|None}``. Any miss, decode
    error, or malformed blob yields the empty payload, so the endpoint always
    answers 200 and the client falls back to the heuristic.
    """
    try:
        raw = await redis.get(CACHE_KEY)
    except Exception:  # pragma: no cover — Redis blip; serve empty, never 500
        logger.warning("generation_estimates.cache_read_failed", exc_info=True)
        return _empty_payload()
    if not raw:
        return _empty_payload()
    try:
        data = json.loads(raw)
        estimates = data.get("estimates")
        if not isinstance(estimates, list):
            return _empty_payload()
        return {
            "estimates": estimates,
            "generated_at": data.get("generated_at"),
        }
    except (ValueError, TypeError, AttributeError):
        logger.warning("generation_estimates.cache_decode_failed", exc_info=True)
        return _empty_payload()


async def refresh_generation_estimates(ctx: dict[str, Any]) -> None:
    """Worker cron body: recompute the cache from the ledger.

    Plain cron — the body catches and logs; a transient blip is recovered by the
    next tick, so a failure must never surface as a worker error.
    """
    if not settings.generation_estimates_enabled:
        return
    from database import AsyncSessionLocal, get_shared_redis  # noqa: PLC0415

    try:
        # Write via the shared client (initialised from settings.redis_url in the
        # worker's on_startup) so the producer and the endpoint's reader use one
        # identical Redis client — no dependence on arq's pool config.
        redis = get_shared_redis()
        async with AsyncSessionLocal() as db:
            count = await refresh_generation_estimates_cache(redis, db)
        logger.info("generation_estimates.refreshed", rows=count)
    except Exception:  # pragma: no cover — best-effort; next tick retries
        logger.warning("generation_estimates.refresh_failed", exc_info=True)

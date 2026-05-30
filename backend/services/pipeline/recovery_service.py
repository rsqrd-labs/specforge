from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_shared_redis
from models import Stage
from services.credit_service import credit_service
from services.pipeline.stage_manager import (
    _POLL_INTERVAL_SECONDS,
    _RECOVERY_LOCK_KEY,
    _RECOVERY_LOCK_TTL,
    CREDIT_COSTS,
    run_recovery_cycle,
)

logger = logging.getLogger(__name__)

_STUCK_THRESHOLD_MINUTES = 3
# _POLL_INTERVAL_SECONDS, _RECOVERY_LOCK_KEY, and _RECOVERY_LOCK_TTL are
# canonical in stage_manager.py and imported above.  H-3 — T-179.


async def recover_stuck_stages(db: AsyncSession) -> int:
    """Reset stages stuck in_progress for >3 min and refund credits. Returns count."""
    cutoff = datetime.now(UTC) - timedelta(minutes=_STUCK_THRESHOLD_MINUTES)

    result = await db.execute(
        select(Stage).where(
            Stage.status == "in_progress",
            Stage.updated_at < cutoff,
        )
    )
    stuck_stages = list(result.scalars())

    recovered = 0
    for stage in stuck_stages:
        credits_refunded = 0
        if stage.deduction_ledger_id is not None:
            await credit_service.refund(db, stage.deduction_ledger_id)
            credits_refunded = CREDIT_COSTS["generate"]

        stage.status = "draft"
        stage.updated_at = datetime.now(UTC)

        logger.warning(
            "stage.recovery stage_id=%s stage_type=%s credits_refunded=%d",
            stage.id,
            stage.type,
            credits_refunded,
        )
        recovered += 1

    if recovered > 0:
        await db.commit()

    # Storyboard generations stuck in 'generating' past their (longer) threshold
    # are recovered in the same leader-locked cycle.  recover_stuck_storyboards
    # commits its own changes independently, so it is safe to run after the stage
    # commit above whether or not any stage was recovered.  Lazy import keeps the
    # pipeline import graph acyclic.  T-254 (Phase 20).
    from services.pipeline.storyboard_service import (  # noqa: PLC0415
        recover_stuck_storyboards,
    )

    recovered += await recover_stuck_storyboards(db)

    return recovered


async def run_recovery_loop() -> None:
    """Background task: polls every 60 seconds and recovers stuck stages.

    Uses a Redis NX lock so only one gunicorn worker runs recovery per cycle.
    Workers that don't acquire the lock skip the cycle silently.
    """
    from database import AsyncSessionLocal

    # Use the shared connection pool — never create a per-loop client.
    # H-1 — T-177.
    redis = get_shared_redis()
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        try:
            acquired = await redis.set(
                _RECOVERY_LOCK_KEY, "1", nx=True, ex=_RECOVERY_LOCK_TTL
            )
            if not acquired:
                continue
            # Continuous heartbeat keeps the lock alive for the full cycle.
            # HF-3 — T-200.
            async with AsyncSessionLocal() as db:
                count = await run_recovery_cycle(redis, db)
                if count > 0:
                    logger.info("stage.recovery.complete recovered=%d", count)
        except Exception:
            logger.exception("stage.recovery.error")

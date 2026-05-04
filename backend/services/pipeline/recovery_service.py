from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Stage
from services.credit_service import credit_service
from services.pipeline.stage_manager import CREDIT_COSTS

logger = logging.getLogger(__name__)

_STUCK_THRESHOLD_MINUTES = 10
_POLL_INTERVAL_SECONDS = 300  # 5 minutes


async def recover_stuck_stages(db: AsyncSession) -> int:
    """Reset stages stuck in_progress for >10 min and refund credits. Returns count."""
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

    return recovered


async def run_recovery_loop() -> None:
    """Background task: polls every 5 minutes and recovers stuck stages."""
    from database import AsyncSessionLocal

    while True:
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                count = await recover_stuck_stages(db)
                if count > 0:
                    logger.info("stage.recovery.complete recovered=%d", count)
        except Exception:
            logger.exception("stage.recovery.error")

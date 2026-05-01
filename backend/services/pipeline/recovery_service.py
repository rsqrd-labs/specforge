from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CreditLedger, Stage, Workspace
from services.credit_service import credit_service

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
        ws_result = await db.execute(
            select(Workspace).where(Workspace.id == stage.workspace_id)
        )
        workspace = ws_result.scalar_one_or_none()
        if workspace is None:
            continue

        # Find the most recent generate/regenerate deduction created within
        # 60s before the stage went in_progress (updated_at tracks that moment).
        ledger_result = await db.execute(
            select(CreditLedger)
            .where(
                CreditLedger.user_id == workspace.user_id,
                CreditLedger.amount < 0,
                CreditLedger.reason.in_(["generate", "regenerate"]),
                CreditLedger.created_at >= stage.updated_at - timedelta(seconds=60),
            )
            .order_by(CreditLedger.created_at.desc())
            .limit(1)
        )
        ledger_entry = ledger_result.scalar_one_or_none()

        credits_refunded = 0
        if ledger_entry is not None:
            await credit_service.refund(db, ledger_entry.id)
            credits_refunded = abs(ledger_entry.amount)

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

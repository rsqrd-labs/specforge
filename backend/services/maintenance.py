"""Periodic data-retention maintenance.

The two webhook idempotency tables — ``github_webhook_events`` and
``stripe_webhook_events`` — grow one row per delivery forever. Each exists only
to deduplicate a provider's at-least-once re-deliveries within that provider's
retry window (GitHub redelivers for a few days; Stripe retries for 72 hours).
Rows older than the retry window can never match an in-flight redelivery, so
they are safe to delete.

:func:`purge_expired_webhook_events` deletes rows older than
:data:`WEBHOOK_EVENT_RETENTION_DAYS` to bound table growth. The retention window
is set well beyond both providers' redelivery windows so dedup protection is
never lost for a delivery still being retried. It runs on the worker's daily
cron (``worker.purge_webhook_events``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.github_webhook_event import GitHubWebhookEvent
from models.stripe_webhook_event import StripeWebhookEvent

logger = structlog.get_logger(__name__)

# Generous relative to GitHub's redelivery window (days) and Stripe's retry
# window (72h): a 30-day floor guarantees a still-retrying delivery always finds
# its dedup row, while bounding unbounded growth of the idempotency tables.
WEBHOOK_EVENT_RETENTION_DAYS = 30


async def purge_expired_webhook_events(
    db: AsyncSession,
    *,
    retention_days: int = WEBHOOK_EVENT_RETENTION_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete webhook idempotency rows older than ``retention_days``.

    Returns the per-table deleted-row counts. Commits once. The cutoff is keyed
    on each table's insert timestamp (``received_at`` for GitHub,
    ``processed_at`` for Stripe).
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)

    github_result = await db.execute(
        delete(GitHubWebhookEvent).where(GitHubWebhookEvent.received_at < cutoff)
    )
    stripe_result = await db.execute(
        delete(StripeWebhookEvent).where(StripeWebhookEvent.processed_at < cutoff)
    )
    await db.commit()

    counts = {
        "github_webhook_events": int(github_result.rowcount or 0),
        "stripe_webhook_events": int(stripe_result.rowcount or 0),
    }
    logger.info(
        "maintenance.webhook_events_purged",
        retention_days=retention_days,
        cutoff=cutoff.isoformat(),
        **counts,
    )
    return counts

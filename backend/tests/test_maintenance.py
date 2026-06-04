"""Tests for the webhook-idempotency retention purge (services.maintenance).

Exercised against the live PostgreSQL instance (same as the other integration
tests). Confirms rows older than the retention window are deleted while rows
inside the provider redelivery window are preserved, so dedup protection is
never lost for an in-flight retry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models.github_webhook_event import GitHubWebhookEvent
from models.stripe_webhook_event import StripeWebhookEvent
from services.maintenance import (
    WEBHOOK_EVENT_RETENTION_DAYS,
    purge_expired_webhook_events,
)


@pytest.mark.asyncio
async def test_purge_deletes_old_rows_keeps_recent() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    tag = uuid4().hex
    now = datetime.now(UTC)
    old = now - timedelta(days=WEBHOOK_EVENT_RETENTION_DAYS + 5)
    recent = now - timedelta(days=1)

    old_gh = f"gh-old-{tag}"
    recent_gh = f"gh-recent-{tag}"
    old_stripe = f"evt-old-{tag}"
    recent_stripe = f"evt-recent-{tag}"

    try:
        async with maker() as db:
            db.add_all(
                [
                    GitHubWebhookEvent(
                        delivery_id=old_gh, event_type="issues", received_at=old
                    ),
                    GitHubWebhookEvent(
                        delivery_id=recent_gh, event_type="issues", received_at=recent
                    ),
                    StripeWebhookEvent(
                        stripe_event_id=old_stripe,
                        event_type="checkout.session.completed",
                        processed_at=old,
                    ),
                    StripeWebhookEvent(
                        stripe_event_id=recent_stripe,
                        event_type="checkout.session.completed",
                        processed_at=recent,
                    ),
                ]
            )
            await db.commit()

        async with maker() as db:
            counts = await purge_expired_webhook_events(db)

        # Both tables purged at least our two old rows.
        assert counts["github_webhook_events"] >= 1
        assert counts["stripe_webhook_events"] >= 1

        async with maker() as db:
            gh_ids = set(
                (
                    await db.execute(
                        select(GitHubWebhookEvent.delivery_id).where(
                            GitHubWebhookEvent.delivery_id.in_([old_gh, recent_gh])
                        )
                    )
                )
                .scalars()
                .all()
            )
            stripe_ids = set(
                (
                    await db.execute(
                        select(StripeWebhookEvent.stripe_event_id).where(
                            StripeWebhookEvent.stripe_event_id.in_(
                                [old_stripe, recent_stripe]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )

        # Old rows gone; recent rows (inside the redelivery window) preserved.
        assert old_gh not in gh_ids
        assert recent_gh in gh_ids
        assert old_stripe not in stripe_ids
        assert recent_stripe in stripe_ids
    finally:
        # Clean up the recent rows we left behind.
        async with maker() as db:
            for model, col, value in (
                (GitHubWebhookEvent, GitHubWebhookEvent.delivery_id, recent_gh),
                (StripeWebhookEvent, StripeWebhookEvent.stripe_event_id, recent_stripe),
            ):
                row = (
                    await db.execute(select(model).where(col == value))
                ).scalar_one_or_none()
                if row is not None:
                    await db.delete(row)
            await db.commit()
        await engine.dispose()

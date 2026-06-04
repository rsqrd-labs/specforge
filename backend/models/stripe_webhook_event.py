"""SQLAlchemy ORM model for stripe_webhook_events.

Every processed Stripe webhook event gets an INSERT here before handle_event
is called.  The UNIQUE constraint on stripe_event_id serialises concurrent
duplicate deliveries: the first INSERT wins; the second raises IntegrityError,
which the webhook handler catches to return {"status": "already_processed"}
without calling handle_event a second time.

INSERT order matters (Phase 18 Payments Directive §5):
    1. INSERT stripe_webhook_events row        ← this model
    2. (on IntegrityError) return already_processed
    3. call stripe_service.handle_event(db, event)

Reversing steps 1 and 3 would create a crash window where a Stripe retry
after a process crash could double-credit the user.

Retention:
    Grows at one row per processed event.  Bounded by the daily retention purge
    (``worker.purge_webhook_events`` → ``services.maintenance``), which deletes
    rows older than ``WEBHOOK_EVENT_RETENTION_DAYS`` (30d) — well beyond Stripe's
    72-hour retry window, so dedup protection is never lost for an in-flight
    retry.

Phase 18 — T-226.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import (  # 'text' required for server_default=text("gen_random_uuid()")
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class StripeWebhookEvent(Base):
    """Idempotency record for a processed Stripe webhook event.

    One row per stripe_event_id.  The UNIQUE constraint on stripe_event_id is
    the write-serialising lock that prevents duplicate event processing.
    """

    __tablename__ = "stripe_webhook_events"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # Stripe's own event ID (e.g. evt_...).  UNIQUE enforced at DB level.
    stripe_event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Event type stored for audit queries (e.g. "checkout.session.completed").
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Wall-clock time this row was inserted (server clock).
    processed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

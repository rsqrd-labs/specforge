"""SQLAlchemy ORM model for github_webhook_events.

Idempotency / dedup record for inbound GitHub webhook deliveries — mirrors
``StripeWebhookEvent``. Every delivery gets an INSERT here before reconciliation
work is enqueued. The UNIQUE constraint on ``delivery_id`` (the
``X-GitHub-Delivery`` header) serialises concurrent duplicate deliveries: the
first INSERT wins; the second raises ``IntegrityError``, which the webhook
handler catches to skip re-processing. This makes every webhook handler
idempotent under GitHub's at-least-once delivery + retry semantics.

INSERT order matters (mirrors the Stripe receiver): record the delivery first,
return early on conflict, only then enqueue the reconcile job. Reversing the
steps creates a crash window where a GitHub retry could double-process.

Retention note:
    Grows at one row per delivery. A future cleanup job should delete rows older
    than GitHub's redelivery window to bound growth (spec §12).

Phase 21 — T-265 / T-266 (spec §10).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class GitHubWebhookEvent(Base):
    """Idempotency record for a processed GitHub webhook delivery.

    One row per ``delivery_id``. The UNIQUE constraint on ``delivery_id`` is the
    write-serialising lock that prevents duplicate event processing.
    """

    __tablename__ = "github_webhook_events"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # The X-GitHub-Delivery header. UNIQUE enforced at DB level (dedup lock).
    delivery_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # e.g. issues | pull_request | installation — stored for audit queries.
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Wall-clock time this row was inserted (server clock).
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Set when the worker finishes reconciliation for this delivery.
    processed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

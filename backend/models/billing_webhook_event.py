"""SQLAlchemy ORM model for billing_webhook_events.

The durable, sanitised inbox for inbound provider webhooks (Lemon ``order_created`` /
``order_refunded`` / etc.). Raw HMAC-verified deliveries are normalised into
``normalized_payload`` (JSONB) — never the raw provider body — and processed on the
arq worker (T-297/T-298). The 4-part identity ``(provider, event_name,
provider_object_id, payload_hash)`` is UNIQUE for duplicate detection under the
provider's at-least-once retry semantics.

Mirrors migration ``0018_billing_neutral_tables.py``; the partial index on the
``received/failed/processing`` pending set lives in the migration. Bounded by the
daily ``purge_billing_events`` retention job (T-298).

Phase 22 — T-291 (Plan §25.6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID as PythonUUID

from sqlalchemy import CheckConstraint, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class BillingWebhookEvent(Base):
    """One sanitised inbound billing webhook (the durable processing inbox)."""

    __tablename__ = "billing_webhook_events"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('lemonsqueezy','stripe')",
            name="ck_bwe_provider",
        ),
        CheckConstraint(
            "status IN ('received','processing','processed','failed')",
            name="ck_bwe_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_bwe_retry_nonneg"),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_object_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_object_id: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of the normalised payload — part of the dedup identity.
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'received'"),
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sanitised, normalised event — NEVER the raw provider body or signature.
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

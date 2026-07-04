"""SQLAlchemy ORM model for billing_checkout_attempts.

One row per checkout intent created by ``POST /billing/checkout`` (T-296). The
``checkout_ref`` is the high-entropy client polling key; only the
``checkout_nonce_hash`` (sha256 of the raw nonce) is stored — the raw nonce never
becomes a column. The signed ``order_created`` webhook is the sole grant authority
(Plan §25 SR3/SR4): a first grant requires the webhook's sanitised custom data to
prove ``checkout_ref`` + the stored nonce hash against this row.

Mirrors migration ``0018_billing_neutral_tables.py`` one-for-one (same CHECKs at the
app level for defence-in-depth, matching the ``StripeCreditPack`` style); the provider
CHECK was widened for Razorpay by ``0034_razorpay_provider.py`` (issue #44). The
partial unique index on ``(provider, provider_checkout_id)`` lives in the migration.

Phase 22 — T-291 (Plan §25.6).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class BillingCheckoutAttempt(Base):
    """A provider-neutral checkout attempt (the attempt-first billing flow).

    Status transitions:
        created → provider_created  (Lemon checkout minted, provider_checkout_id set)
        provider_created → completed (signed order_created webhook granted the pack)
        created/provider_created → expired  (TTL lapsed, swept by purge_billing_events)
        created/provider_created → failed   (provider error / orphaned checkout)
    """

    __tablename__ = "billing_checkout_attempts"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('lemonsqueezy','stripe','razorpay')",
            name="ck_bca_provider",
        ),
        CheckConstraint("credits > 0", name="ck_bca_credits_positive"),
        CheckConstraint("price_cents > 0", name="ck_bca_price_positive"),
        CheckConstraint("validity_days > 0", name="ck_bca_validity_positive"),
        CheckConstraint(
            "status IN ('created','provider_created','completed','expired','failed')",
            name="ck_bca_status",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # High-entropy polling key. UNIQUE — the client polls /billing/status by it.
    checkout_ref: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # Lemon checkout id; NULL until the provider checkout is minted.
    provider_checkout_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # sha256(checkout_nonce) — never the raw nonce (SR4).
    checkout_nonce_hash: Mapped[str] = mapped_column(Text, nullable=False)

    # Economics snapshot — the grant is validated against THESE values (the
    # attempt snapshot), not live config, so an in-flight price change is safe.
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'created'"),
    )
    provider_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    success_redirect_seen_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

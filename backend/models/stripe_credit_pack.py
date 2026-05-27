"""SQLAlchemy ORM model for stripe_credit_packs.

Each row represents one Stripe Checkout purchase.  credits_remaining is
decremented by CreditService._drain_packs() in FIFO order (soonest-expiring
first, ORDER BY expires_at ASC) whenever CreditService.deduct() is called.
Lazy expiry in CreditService._expire_user_packs() sweeps rows whose expires_at
has passed, setting status='expired' and credits_remaining=0.

Phase 18 — T-226.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import CheckConstraint, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class StripeCreditPack(Base):
    """One credit pack purchased via Stripe Checkout.

    Status transitions:
        active    → consumed  (credits_remaining reaches 0 via FIFO drain)
        active    → expired   (expires_at < now(), swept by lazy expiry)
        active    → disputed  (charge.dispute.created webhook received)

    The three CHECK constraints are enforced at both the DB level (here) and
    the application level (CreditService) for defence-in-depth.
    """

    __tablename__ = "stripe_credit_packs"
    __table_args__ = (
        CheckConstraint(
            "credits_remaining >= 0",
            name="ck_stripe_credit_packs_remaining_nonneg",
        ),
        CheckConstraint(
            "credits_remaining <= credits_purchased",
            name="ck_stripe_credit_packs_remaining_leq_purchased",
        ),
        CheckConstraint(
            "status IN ('active','consumed','expired','disputed')",
            name="ck_stripe_credit_packs_status",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # FK → users.id (CASCADE DELETE).  UUID stored as native PostgreSQL UUID.
    user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    # Stripe Checkout Session ID (e.g. cs_test_...).  Unique: one pack per session.
    stripe_session_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Stripe Payment Intent ID (e.g. pi_...).  Used to correlate dispute events.
    # Nullable: may be absent for some payment methods until capture.
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Credits accounting.
    credits_purchased: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Pack lifecycle state.  DB-level CHECK constraint enforces valid values.
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'active'"),
    )

    # purchased_at: set from event["created"] in the webhook handler so the
    # 30-day window is anchored to the Stripe payment time, not delivery time.
    purchased_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # expires_at: purchased_at + 30 days (settings.stripe_credit_validity_days).
    # Derived from event["created"] in the webhook handler — NOT datetime.utcnow().
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

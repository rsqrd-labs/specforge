"""SQLAlchemy ORM model for billing_credit_debts.

A recoverable negative balance created when a reversal (refund/dispute) revokes more
credits than a pack still has remaining (Plan §25 DC5). One debt row per source pack
(``source_pack_id`` UNIQUE); the FK is ``ON DELETE RESTRICT`` so debt is never silently
lost on pack deletion. A later purchase's grant pays debt first (``credits_recovered``
climbs toward ``credits_owed``; ``status`` flips to ``recovered``).

Mirrors migration ``0018_billing_neutral_tables.py`` (same CHECK at app level); the
provider CHECK was widened for Razorpay by ``0034_razorpay_provider.py`` (issue #44).

Phase 22 — T-291 (Plan §25.6).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class BillingCreditDebt(Base):
    """Recoverable debt from a reversed pack (expired value never becomes debt)."""

    __tablename__ = "billing_credit_debts"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('lemonsqueezy','stripe','razorpay')",
            name="ck_bcd_provider",
        ),
        CheckConstraint("credits_owed > 0", name="ck_bcd_owed_positive"),
        CheckConstraint("credits_recovered >= 0", name="ck_bcd_recovered_nonneg"),
        CheckConstraint(
            "status IN ('pending','recovered')",
            name="ck_bcd_status",
        ),
        CheckConstraint(
            "credits_recovered <= credits_owed",
            name="ck_bcd_recovered_leq_owed",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # One debt per reversed pack. RESTRICT: debt cannot be orphaned by pack deletion.
    source_pack_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("billing_credit_packs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    credits_owed: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_recovered: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

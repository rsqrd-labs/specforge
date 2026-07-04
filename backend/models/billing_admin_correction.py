"""SQLAlchemy ORM model for billing_admin_corrections.

The append-only audit trail for the exceptional, evidence-backed admin support path
(T-302): a manual credit grant for an order the automatic webhook pipeline could not
settle. UNIQUE on ``(provider, provider_order_id)`` so a correction cannot be applied
twice for the same order. The user FKs are ``ON DELETE RESTRICT`` (audit integrity:
a user with correction rows cannot be hard-deleted without settlement — Plan §25.6).

There are deliberately **no** UPDATE/DELETE application paths — rows are written once.

Mirrors migration ``0018_billing_neutral_tables.py``; the provider CHECK was widened
for Razorpay by ``0034_razorpay_provider.py`` (issue #44).

Phase 22 — T-291 (Plan §25.6).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class BillingAdminCorrection(Base):
    """One append-only admin credit correction (evidence-backed support grant)."""

    __tablename__ = "billing_admin_corrections"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('lemonsqueezy','stripe','razorpay')",
            name="ck_bac_provider",
        ),
        CheckConstraint("credits > 0", name="ck_bac_credits_positive"),
        CheckConstraint("price_cents > 0", name="ck_bac_price_positive"),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # The acting admin (allowlist-authorised at the router) and the credited user.
    admin_user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The pack created by the correction (NULL if the grant did not mint a pack).
    billing_credit_pack_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("billing_credit_packs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_order_id: Mapped[str] = mapped_column(Text, nullable=False)

    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

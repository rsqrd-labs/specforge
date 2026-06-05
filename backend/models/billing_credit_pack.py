"""SQLAlchemy ORM model for billing_credit_packs.

The provider-neutral successor to ``StripeCreditPack``. One row per purchased credit
pack; ``credits_remaining`` is drained FIFO (soonest-expiring first) by
``CreditService`` (T-294), lazy expiry moves lapsed credits into ``credits_expired``,
debt recovery into ``credits_debt_recovered``, and exactly-once proportional reversals
into ``credits_revoked``. The full lifetime accounting set drives the conservation
invariant ``remaining + consumed + expired + debt_recovered <= purchased``.

Mirrors migration ``0018_billing_neutral_tables.py`` one-for-one — the same CHECK
constraints are declared here for defence-in-depth (matching the ``StripeCreditPack``
style). The partial unique idempotency indexes on ``(provider, provider_order_id)`` and
``(provider, provider_checkout_id)`` live in the migration.

Phase 22 — T-291 (Plan §25.6).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class BillingCreditPack(Base):
    """One provider-neutral credit pack.

    Status union: ``active|consumed|expired|refunded|disputed``. ``refunded`` and
    ``disputed`` are reached by the reversal paths (T-300); the backfill (T-290) also
    seeds legacy ``disputed`` rows with ``credits_revoked=0`` (revoke is never inferred
    from ``credits_remaining``).
    """

    __tablename__ = "billing_credit_packs"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('lemonsqueezy','stripe')",
            name="ck_bcp_provider",
        ),
        CheckConstraint("credits_purchased > 0", name="ck_bcp_purchased_positive"),
        CheckConstraint("credits_remaining >= 0", name="ck_bcp_remaining_nonneg"),
        CheckConstraint("credits_consumed >= 0", name="ck_bcp_consumed_nonneg"),
        CheckConstraint("credits_expired >= 0", name="ck_bcp_expired_nonneg"),
        CheckConstraint(
            "credits_debt_recovered >= 0", name="ck_bcp_debt_recovered_nonneg"
        ),
        CheckConstraint("credits_revoked >= 0", name="ck_bcp_revoked_nonneg"),
        CheckConstraint("price_cents > 0", name="ck_bcp_price_positive"),
        CheckConstraint("paid_item_amount_cents > 0", name="ck_bcp_paid_item_positive"),
        CheckConstraint(
            "provider_order_total_cents IS NULL OR provider_order_total_cents >= 0",
            name="ck_bcp_order_total_nonneg",
        ),
        CheckConstraint(
            "provider_refunded_total_cents_seen >= 0",
            name="ck_bcp_refunded_total_nonneg",
        ),
        CheckConstraint(
            "refunded_item_amount_cents_processed >= 0",
            name="ck_bcp_refunded_item_nonneg",
        ),
        CheckConstraint(
            "status IN ('active','consumed','expired','refunded','disputed')",
            name="ck_bcp_status",
        ),
        CheckConstraint(
            "credits_remaining <= credits_purchased",
            name="ck_bcp_remaining_leq_purchased",
        ),
        CheckConstraint(
            "credits_remaining + credits_consumed + credits_expired "
            "+ credits_debt_recovered <= credits_purchased",
            name="ck_bcp_accounting_sum",
        ),
        CheckConstraint(
            "refunded_item_amount_cents_processed <= paid_item_amount_cents",
            name="ck_bcp_refunded_item_leq_paid",
        ),
        CheckConstraint(
            "provider_order_total_cents IS NULL "
            "OR provider_refunded_total_cents_seen <= provider_order_total_cents",
            name="ck_bcp_refunded_total_leq_order",
        ),
        CheckConstraint(
            "credits_revoked <= credits_purchased",
            name="ck_bcp_revoked_leq_purchased",
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
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_checkout_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_variant_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifetime accounting set.
    credits_purchased: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_consumed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    credits_expired: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    credits_debt_recovered: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    credits_revoked: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    # Economics. price_cents is the SpecForge-authoritative pack price;
    # paid_item_amount_cents is the validated line-item amount; provider_order_total
    # is the order gross (NULL when unknown) used to cap refunds seen.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    paid_item_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_order_total_cents: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    provider_refunded_total_cents_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    refunded_item_amount_cents_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'active'"),
    )
    purchased_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

"""SQLAlchemy ORM model for billing_reconciliation_cursors.

The authoritative, durable state for the periodic three-lane reconcile job (T-301) —
stored in Postgres, not Redis, so it survives a cache flush. ``provider`` is the
primary key and is ``lemonsqueezy``-only (it never holds a ``stripe`` row); the
migration seeds the single ``('lemonsqueezy')`` row. ``last_successful_run_at`` bounds
how far back lane-2 scans the provider's order list.

Mirrors migration ``0018_billing_neutral_tables.py``.

Phase 22 — T-291 (Plan §25.6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class BillingReconciliationCursor(Base):
    """The single lemonsqueezy reconcile cursor (one row, provider is the PK)."""

    __tablename__ = "billing_reconciliation_cursors"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('lemonsqueezy')",
            name="ck_brc_provider",
        ),
    )

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    last_successful_run_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("'1970-01-01 00:00:00+00'"),
    )
    last_run_started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    last_run_completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

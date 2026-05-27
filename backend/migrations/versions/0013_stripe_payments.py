"""Create stripe_credit_packs and stripe_webhook_events tables.

stripe_credit_packs
    Tracks every credit pack purchased via Stripe Checkout.  Each pack carries
    its own expiry window (30 days from purchase timestamp) and a credits_remaining
    counter that is drained in FIFO order (soonest-expiring first) by
    CreditService._drain_packs().  The CHECK constraints mirror those on the ORM
    model and provide defence-in-depth at the DB level.

stripe_webhook_events
    Idempotency log for processed Stripe webhook events.  The UNIQUE constraint
    on stripe_event_id serialises concurrent duplicate deliveries at the DB level:
    the first INSERT wins; the second raises IntegrityError, which the webhook
    handler catches to return an "already_processed" response without double-crediting.

Retention note (T-226):
    stripe_webhook_events grows at one row per processed webhook.  Stripe retries
    events for up to 72 hours; beyond that the row is only needed for forensic audit.
    A periodic cleanup job should be added in a future phase:

        DELETE FROM stripe_webhook_events
        WHERE processed_at < NOW() - INTERVAL '30 days';

    -- TODO: add retention cleanup for stripe_webhook_events (Phase 18+)

Phase 18 — T-226.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # stripe_credit_packs
    # -----------------------------------------------------------------------
    op.create_table(
        "stripe_credit_packs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stripe_session_id", sa.VARCHAR(), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.VARCHAR(), nullable=True),
        sa.Column("credits_purchased", sa.Integer(), nullable=False),
        sa.Column("credits_remaining", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "purchased_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "expires_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "credits_remaining >= 0",
            name="ck_stripe_credit_packs_remaining_nonneg",
        ),
        sa.CheckConstraint(
            "credits_remaining <= credits_purchased",
            name="ck_stripe_credit_packs_remaining_leq_purchased",
        ),
        sa.CheckConstraint(
            "status IN ('active','consumed','expired','disputed')",
            name="ck_stripe_credit_packs_status",
        ),
    )

    # Basic user_id index for general pack lookups.
    op.create_index(
        "ix_stripe_credit_packs_user_id",
        "stripe_credit_packs",
        ["user_id"],
    )

    # Partial index on active packs ordered by expires_at.
    # _expire_user_packs() and _drain_packs() both filter
    # WHERE user_id = ? AND status = 'active' ORDER BY expires_at ASC.
    # The partial index (WHERE status = 'active') keeps the index small —
    # consumed/expired/disputed packs are excluded automatically.
    op.create_index(
        "ix_stripe_credit_packs_user_active",
        "stripe_credit_packs",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # Unique constraint: one credit pack per Stripe Checkout Session.
    # Prevents a race between two concurrent checkout.session.completed
    # deliveries for the same session from creating two packs.
    op.create_unique_constraint(
        "uq_stripe_credit_packs_session_id",
        "stripe_credit_packs",
        ["stripe_session_id"],
    )

    # -----------------------------------------------------------------------
    # stripe_webhook_events
    # -----------------------------------------------------------------------
    # -- TODO: add retention cleanup for stripe_webhook_events (Phase 18+) --
    op.create_table(
        "stripe_webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("stripe_event_id", sa.VARCHAR(), nullable=False),
        sa.Column("event_type", sa.VARCHAR(), nullable=False),
        sa.Column(
            "processed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # UNIQUE on stripe_event_id is the idempotency serialisation lock.
    # The webhook handler does INSERT ... then handle_event; a concurrent
    # delivery of the same event hits IntegrityError here and returns
    # {"status": "already_processed"} without calling handle_event.
    op.create_unique_constraint(
        "uq_stripe_webhook_events_stripe_event_id",
        "stripe_webhook_events",
        ["stripe_event_id"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order.
    # stripe_webhook_events has no FK dependencies; drop it first.
    op.drop_constraint(
        "uq_stripe_webhook_events_stripe_event_id",
        "stripe_webhook_events",
        type_="unique",
    )
    op.drop_table("stripe_webhook_events")

    # stripe_credit_packs references users.id via FK.
    op.drop_constraint(
        "uq_stripe_credit_packs_session_id",
        "stripe_credit_packs",
        type_="unique",
    )
    op.drop_index(
        "ix_stripe_credit_packs_user_active",
        table_name="stripe_credit_packs",
    )
    op.drop_index(
        "ix_stripe_credit_packs_user_id",
        table_name="stripe_credit_packs",
    )
    op.drop_table("stripe_credit_packs")

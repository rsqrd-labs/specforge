"""Replace broad UNIQUE(user_id, reason) with partial index on refund rows only.

Migration 0003 added UNIQUE(user_id, reason) to prevent double-refunds.
That constraint inadvertently blocks users from making more than one deduction
with the same reason string (e.g. "generate"), breaking the core LLM pipeline.

The fix: drop the broad constraint and replace it with a partial unique index
scoped exclusively to rows whose reason starts with "refund:". This preserves
idempotency for refunds while allowing unlimited normal deductions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the overly-broad constraint added in 0003 that prevents repeat deductions
    op.drop_constraint(
        "uq_credit_ledger_user_reason",
        "credit_ledger",
        type_="unique",
    )
    # Replace with a partial index scoped to refund rows only
    op.execute("""
        CREATE UNIQUE INDEX uq_credit_ledger_refund_reason
        ON credit_ledger (user_id, reason)
        WHERE reason LIKE 'refund:%'
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_credit_ledger_refund_reason")
    op.create_unique_constraint(
        "uq_credit_ledger_user_reason",
        "credit_ledger",
        ["user_id", "reason"],
    )

"""Add unique constraint on credit_ledger(user_id, reason) to prevent double-refunds.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_credit_ledger_user_reason",
        "credit_ledger",
        ["user_id", "reason"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_credit_ledger_user_reason",
        "credit_ledger",
        type_="unique",
    )

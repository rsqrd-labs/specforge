"""Add denormalized user credit balances.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "credit_balance",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE users
        SET credit_balance = COALESCE(ledger.balance, 0)
        FROM (
            SELECT user_id, SUM(amount) AS balance
            FROM credit_ledger
            GROUP BY user_id
        ) AS ledger
        WHERE users.id = ledger.user_id
        """
    )
    op.create_check_constraint(
        "ck_users_credit_balance_nonnegative",
        "users",
        "credit_balance >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_credit_balance_nonnegative",
        "users",
        type_="check",
    )
    op.drop_column("users", "credit_balance")

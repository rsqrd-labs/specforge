"""Add deduction_ledger_id FK column to stages for exact recovery refunds.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stages",
        sa.Column(
            "deduction_ledger_id",
            UUID(as_uuid=True),
            sa.ForeignKey("credit_ledger.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("stages", "deduction_ledger_id")

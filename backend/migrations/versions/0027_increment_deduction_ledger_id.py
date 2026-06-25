"""Add deduction_ledger_id FK column to increments for recovery refunds.

Increment generation becomes charge-then-generate: the deduction is committed
BEFORE the slow LLM call so the user-row FOR UPDATE lock is not held across it
(audit finding #6). That makes an orphan-recovery sweep load-bearing — a hard
process death can now strand a committed charge against a 'generating' increment
(finding #7). This column pins the deduction ledger row so the sweep can refund
it idempotently, mirroring stages.deduction_ledger_id (migration 0004).

Pure additive backfill: nullable, no default. Existing increment rows predate the
charge-then-generate flow and simply leave it NULL; the sweep skips a NULL ledger.

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "increments",
        sa.Column(
            "deduction_ledger_id",
            UUID(as_uuid=True),
            sa.ForeignKey("credit_ledger.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("increments", "deduction_ledger_id")

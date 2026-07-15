"""Track completion of inbound GitHub reconciliation.

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "integration_pushes",
        sa.Column("last_inbound_sync_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "integration_pushes",
        sa.Column("last_inbound_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_pushes", "last_inbound_sync_error")
    op.drop_column("integration_pushes", "last_inbound_sync_at")

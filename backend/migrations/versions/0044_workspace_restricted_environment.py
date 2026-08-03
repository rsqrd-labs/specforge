"""Workspace restricted_environment column (Demo Day locked-down environments).

Adds ``restricted_environment`` — a Demo-Day-gated, create-time-only boolean
mirroring the ``mode``/``target_agent``/``time_budget_minutes`` family added in
migration 0029. When true, generation must avoid Docker/containers/VMs and any
admin/sudo install step (a hackathon venue that disallows installing Docker).
NOT NULL with a server default of ``false`` so every existing row backfills to
the current, unconstrained behavior without a data migration.

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "restricted_environment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "restricted_environment")

"""Workspace disable_critic flag.

T-247 (Phase 19). Owner-only escape hatch for the critic quality gate. When a
workspace owner sets this flag the stage_manager skips the critic second-pass
for that workspace. NOT NULL with a server default of false so every existing
row backfills to "gate enabled" without a data migration.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "disable_critic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "disable_critic")

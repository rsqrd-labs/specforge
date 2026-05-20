"""Add gap_patch_used flag to stages.

Tracks whether a harness stage has consumed its one free coverage-gap
regeneration. Server-authoritative so the gate survives refresh, cache
eviction, and cross-device sessions.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stages",
        sa.Column(
            "gap_patch_used",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("stages", "gap_patch_used")

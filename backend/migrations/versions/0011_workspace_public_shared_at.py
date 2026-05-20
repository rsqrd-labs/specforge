"""Workspace public_shared_at timestamp.

T-USE-09 / T-168. Records the most-recent enable/rotate moment for the
public share so the public view's ETag and `Cache-Control` directives
can use a stable bumper. We can't reuse `updated_at` because that also
bumps on workspace renames, problem_statement edits, etc. — bumping the
ETag on every unrelated edit would defeat the cache.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-21
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "public_shared_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "public_shared_at")

"""Workspace brave_research_enabled flag.

Issue #12 (Phase 3). Per-workspace opt-in for Brave web-research enrichment.
Sending a workspace's idea text to Brave is a third-party data egress and a
credit charge, so it is strictly opt-in — off by default, never inferred.
NOT NULL with a server default of false so every existing row backfills to
"research disabled" without a data migration, keeping the feature dark.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "brave_research_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "brave_research_enabled")

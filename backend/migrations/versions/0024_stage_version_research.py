"""StageVersion Brave research provenance columns.

Issue #12 (Phase 4). Persist the injected research block + its source list on the
StageVersion so a grounded generation is reproducible/diffable and can show its
provenance. Both columns are nullable with no default: a version without
grounding (the overwhelming majority — feature off / not opted in / cache hit
with no research / user edits) simply leaves them NULL, so this is a pure
additive backfill with zero data migration and the feature stays dark.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stage_versions",
        sa.Column("research_context", sa.Text(), nullable=True),
    )
    op.add_column(
        "stage_versions",
        sa.Column("research_sources", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stage_versions", "research_sources")
    op.drop_column("stage_versions", "research_context")

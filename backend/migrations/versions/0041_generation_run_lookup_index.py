"""Index generation history lookups by stage and start time.

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_stage_generation_runs_stage_started_at",
        "stage_generation_runs",
        ["stage_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stage_generation_runs_stage_started_at",
        table_name="stage_generation_runs",
    )

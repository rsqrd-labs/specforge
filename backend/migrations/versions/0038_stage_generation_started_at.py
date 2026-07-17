"""Add stages.generation_started_at + generation_action (honest elapsed baseline).

The streaming overlay's elapsed timer needs a *stable* generation start instant
that survives a page refresh. Until now the frontend reconstructed it from
``stages.updated_at``, but the DB heartbeat (``_stage_db_heartbeat``) bumps that
column every 30s to keep the recovery sweep from killing a live generation —
so the reconstructed baseline sawtoothed back to ~0 every reconnect poll
(RC-1). This adds a dedicated, write-once ``generation_started_at`` stamped at
the ``in_progress`` transition and never touched by the heartbeat, plus
``generation_action`` so a reconnect overlay after refresh can show the correct
operation label (generate vs regenerate) instead of always "generate" (A6).

Both columns are nullable and additive: existing rows are NULL, and the frontend
treats NULL as "unknown" and falls back to the (now ref-pinned) ``updated_at``
baseline. The recovery sweep is unchanged — it still keys on ``updated_at`` — so
this is zero-risk to stuck-stage recovery.

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stages",
        sa.Column(
            "generation_started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "stages",
        sa.Column(
            "generation_action",
            sa.String(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("stages", "generation_action")
    op.drop_column("stages", "generation_started_at")

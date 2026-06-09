"""Persist per-stage quality gate state.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stages",
        sa.Column(
            "quality_gate_status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'clear'"),
        ),
    )
    op.add_column(
        "stages",
        sa.Column("quality_gate_kind", sa.String(), nullable=True),
    )
    op.add_column(
        "stages",
        sa.Column(
            "quality_gate_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "stages",
        sa.Column("quality_gate_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "stages",
        sa.Column(
            "quality_gate_failed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_stages_quality_gate_status",
        "stages",
        "quality_gate_status IN ('clear', 'blocked', 'overridden')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stages_quality_gate_status", "stages", type_="check")
    op.drop_column("stages", "quality_gate_failed_at")
    op.drop_column("stages", "quality_gate_version")
    op.drop_column("stages", "quality_gate_payload")
    op.drop_column("stages", "quality_gate_kind")
    op.drop_column("stages", "quality_gate_status")

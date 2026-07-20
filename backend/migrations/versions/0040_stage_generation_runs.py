"""Add durable, cancellable stage-generation runs and chunk checkpoints.

Revision ID: 0040
Revises: 0039
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``checking`` means the usable draft is persisted and visible while the
    # bounded external technology lookup finishes. It is deliberately distinct
    # from ``blocked`` so the UI never presents a pending check as a failure.
    op.drop_constraint("ck_stages_quality_gate_status", "stages", type_="check")
    op.create_check_constraint(
        "ck_stages_quality_gate_status",
        "stages",
        "quality_gate_status IN "
        "('clear', 'checking', 'blocked', 'overridden', 'advisory')",
    )

    op.create_table(
        "stage_generation_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deduction_ledger_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), server_default=sa.text("'running'"), nullable=False
        ),
        sa.Column(
            "phase", sa.String(), server_default=sa.text("'preparing'"), nullable=False
        ),
        sa.Column("previous_status", sa.String(), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=False),
        sa.Column(
            "completed_parts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("total_parts", sa.Integer(), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column(
            "partial_saved",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "refunded_credits",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deadline_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "heartbeat_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cancel_requested_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('generate', 'regenerate')",
            name="ck_stage_generation_runs_action",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'blocked', 'cancelled', "
            "'timed_out', 'failed')",
            name="ck_stage_generation_runs_status",
        ),
        sa.CheckConstraint(
            "phase IN ('preparing', 'drafting', 'assembling', 'validating', "
            "'saving', 'stopping', 'complete')",
            name="ck_stage_generation_runs_phase",
        ),
        sa.CheckConstraint(
            "previous_status IN ('draft', 'stale')",
            name="ck_stage_generation_runs_previous_status",
        ),
        sa.CheckConstraint(
            "completed_parts >= 0 AND total_parts >= 0 "
            "AND completed_parts <= total_parts",
            name="ck_stage_generation_runs_progress",
        ),
        sa.CheckConstraint(
            "refunded_credits >= 0",
            name="ck_stage_generation_runs_refunded_credits",
        ),
        sa.ForeignKeyConstraint(["stage_id"], ["stages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["deduction_ledger_id"], ["credit_ledger.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_stage_generation_runs_active_stage",
        "stage_generation_runs",
        ["stage_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_stage_generation_runs_active_deadline",
        "stage_generation_runs",
        ["deadline_at"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_stage_generation_runs_active_heartbeat",
        "stage_generation_runs",
        ["heartbeat_at"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "stage_generation_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("generation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_key", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column(
            "retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_stage_generation_chunks_ordinal"),
        sa.ForeignKeyConstraint(
            ["generation_run_id"],
            ["stage_generation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_run_id",
            "chunk_key",
            name="uq_stage_generation_chunks_run_key",
        ),
        sa.UniqueConstraint(
            "generation_run_id",
            "ordinal",
            name="uq_stage_generation_chunks_run_ordinal",
        ),
    )


def downgrade() -> None:
    op.drop_table("stage_generation_chunks")
    op.drop_index(
        "ix_stage_generation_runs_active_heartbeat",
        table_name="stage_generation_runs",
    )
    op.drop_index(
        "ix_stage_generation_runs_active_deadline",
        table_name="stage_generation_runs",
    )
    op.drop_index(
        "uq_stage_generation_runs_active_stage",
        table_name="stage_generation_runs",
    )
    op.drop_table("stage_generation_runs")
    op.drop_constraint("ck_stages_quality_gate_status", "stages", type_="check")
    op.create_check_constraint(
        "ck_stages_quality_gate_status",
        "stages",
        "quality_gate_status IN ('clear', 'blocked', 'overridden', 'advisory')",
    )

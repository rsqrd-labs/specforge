"""Create llm_cost_events table (Phase 0 of issue #26 — LLM cost ledger).

One append-only row per LLM provider call, capturing tokens (incl. a
reasoning breakout that is already inside output_tokens), estimated cost,
latency, finish reason, routing flags, retry/repair counts, the post-gate
quality outcome, and foreign keys to the product surface (workspace / stage /
storyboard / increment) for cost rollups.

Foreign keys use ON DELETE SET NULL so cost history survives entity deletion,
matching the billing-audit retention pattern. Columns/indexes mirror
models/llm_cost_event.py one-for-one to keep the ORM and schema from drifting.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_cost_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("generation_id", sa.Text(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_tier", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("stage_type", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_estimation_method", sa.Text(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.Text(), nullable=True),
        sa.Column(
            "stopped_by_limit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "cache_hit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "batch",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "cross_provider_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("repair_count", sa.Integer(), nullable=True),
        sa.Column("quality_outcome", sa.Text(), nullable=True),
        sa.Column("credit_reason", sa.Text(), nullable=True),
        sa.Column("product_surface", sa.Text(), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("storyboard_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("increment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["stage_id"], ["stages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["storyboard_id"], ["storyboards.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["increment_id"], ["increments.id"], ondelete="SET NULL"
        ),
    )

    op.create_index("ix_llm_cost_events_created_at", "llm_cost_events", ["created_at"])
    op.create_index(
        "ix_llm_cost_events_generation_id", "llm_cost_events", ["generation_id"]
    )
    op.create_index("ix_llm_cost_events_operation", "llm_cost_events", ["operation"])
    op.create_index(
        "ix_llm_cost_events_quality_outcome", "llm_cost_events", ["quality_outcome"]
    )
    op.create_index(
        "ix_llm_cost_events_product_surface", "llm_cost_events", ["product_surface"]
    )
    op.create_index(
        "ix_llm_cost_events_workspace_id", "llm_cost_events", ["workspace_id"]
    )
    op.create_index("ix_llm_cost_events_stage_id", "llm_cost_events", ["stage_id"])
    op.create_index(
        "ix_llm_cost_events_storyboard_id", "llm_cost_events", ["storyboard_id"]
    )
    op.create_index(
        "ix_llm_cost_events_increment_id", "llm_cost_events", ["increment_id"]
    )
    # Rollup helper: cost-by-model/provider scans newest-first.
    op.create_index(
        "ix_llm_cost_events_provider_model_created_at",
        "llm_cost_events",
        ["provider", "model", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_cost_events_provider_model_created_at", table_name="llm_cost_events"
    )
    op.drop_index("ix_llm_cost_events_increment_id", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_storyboard_id", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_stage_id", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_workspace_id", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_product_surface", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_quality_outcome", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_operation", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_generation_id", table_name="llm_cost_events")
    op.drop_index("ix_llm_cost_events_created_at", table_name="llm_cost_events")
    op.drop_table("llm_cost_events")

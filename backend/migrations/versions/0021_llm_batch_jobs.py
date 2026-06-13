"""Create llm_batch_jobs table (Phase 3 of issue #26 — deferred batch eval).

One durable checkpoint per non-interactive judge/eval call submitted through the
provider Message Batches API. The provider bills a batch whether or not its
results are collected, so the ``provider_batch_id`` is persisted the moment the
batch is created. The worker drives ``pending → submitted → completed | failed``;
a successful collect deletes the row (the durable artifact is the persisted
EvalResult), a terminal failure leaves it ``failed`` and dead-letters.

The workspace FK uses ON DELETE SET NULL so an in-flight batch survives a
workspace deletion (it still completes and records cost). Columns/indexes mirror
models/llm_batch_job.py one-for-one.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_batch_jobs",
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
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_tier", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("provider_batch_id", sa.Text(), nullable=True),
        sa.Column("custom_id", sa.Text(), nullable=False),
        sa.Column("request_system", sa.Text(), nullable=False),
        sa.Column("request_user", sa.Text(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_llm_batch_jobs_created_at", "llm_batch_jobs", ["created_at"])
    op.create_index("ix_llm_batch_jobs_status", "llm_batch_jobs", ["status"])
    op.create_index(
        "ix_llm_batch_jobs_provider_batch_id", "llm_batch_jobs", ["provider_batch_id"]
    )
    op.create_index(
        "ix_llm_batch_jobs_workspace_id", "llm_batch_jobs", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_batch_jobs_workspace_id", table_name="llm_batch_jobs")
    op.drop_index("ix_llm_batch_jobs_provider_batch_id", table_name="llm_batch_jobs")
    op.drop_index("ix_llm_batch_jobs_status", table_name="llm_batch_jobs")
    op.drop_index("ix_llm_batch_jobs_created_at", table_name="llm_batch_jobs")
    op.drop_table("llm_batch_jobs")

"""Increments + idea backlog, and the deferred increment FKs (Phase 21 — T-278).

Lands the living-workspace schema (``V1 spec.md`` v2.0.0 §10, §4.14.7):

New tables:
- ``increments``      — a versioned delta layered on a finalised baseline; unique
  on ``(workspace_id, sequence)``. ``baseline_version_ids`` (JSONB) pins the
  immutable ``StageVersion.id`` values delta generation treats as fixed context.
- ``increment_ideas`` — the lightweight feature backlog batched into increments.

Deferred FKs from ``0016``: ``integration_pushes.increment_id`` and
``integration_push_tasks.increment_id`` were created as plain UUID columns in
0016 (the ``increments`` table did not exist yet). This migration adds their FK
constraints → ``increments.id`` (``ON DELETE SET NULL`` so a push/task survives
the removal of an increment, reverting to "no increment").

Constraints mirror ``models/increment.py`` one-for-one to keep the ORM and schema
from drifting.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_PUSHES = "fk_integration_pushes_increment_id"
_FK_PUSH_TASKS = "fk_integration_push_tasks_increment_id"


def upgrade() -> None:
    # --- increments ---------------------------------------------------------
    op.create_table(
        "increments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 1, 2, 3… per workspace.
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        # draft | generating | ready | pushed | stale
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        # Immutable StageVersion.id values forming the baseline delta context.
        sa.Column(
            "baseline_version_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "sequence",
            name="uq_increment_workspace_sequence",
        ),
    )
    op.create_index(
        "ix_increments_workspace_id",
        "increments",
        ["workspace_id"],
    )

    # --- increment_ideas ----------------------------------------------------
    op.create_table(
        "increment_ideas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Set when the idea is pulled into an increment.
        sa.Column("increment_id", postgresql.UUID(as_uuid=True), nullable=True),
        # user | github
        sa.Column("source", sa.Text(), nullable=False),
        # e.g. gh-issue:123 when sourced from GitHub.
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        # open | planned | done | dismissed
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["increment_id"],
            ["increments.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_increment_ideas_workspace_id",
        "increment_ideas",
        ["workspace_id"],
    )

    # --- deferred FKs from 0016 (increment_id → increments.id) ---------------
    op.create_foreign_key(
        _FK_PUSHES,
        "integration_pushes",
        "increments",
        ["increment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        _FK_PUSH_TASKS,
        "integration_push_tasks",
        "increments",
        ["increment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop the deferred FKs before the increments table they reference.
    op.drop_constraint(_FK_PUSH_TASKS, "integration_push_tasks", type_="foreignkey")
    op.drop_constraint(_FK_PUSHES, "integration_pushes", type_="foreignkey")

    op.drop_index("ix_increment_ideas_workspace_id", table_name="increment_ideas")
    op.drop_table("increment_ideas")
    op.drop_index("ix_increments_workspace_id", table_name="increments")
    op.drop_table("increments")

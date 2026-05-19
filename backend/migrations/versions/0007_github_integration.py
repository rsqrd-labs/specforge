"""GitHub integration tables.

Adds three tables for Phase 13 GitHub export integration:

- user_integrations: stores per-user Fernet-encrypted OAuth tokens.
- integration_pushes: one row per (workspace, provider); idempotent re-export.
- integration_push_tasks: maps T-NNN task refs to GitHub Issue numbers
  so re-exports update issues in place instead of creating duplicates.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_integrations",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("github_username", sa.Text(), nullable=True),
        sa.Column(
            "connected_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            name="uq_user_integration_provider",
        ),
    )
    op.create_index(
        "ix_user_integrations_user_id",
        "user_integrations",
        ["user_id"],
    )

    op.create_table(
        "integration_pushes",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("repo_full_name", sa.Text(), nullable=True),
        sa.Column("repo_url", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "pushed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            name="uq_integration_push_workspace_provider",
        ),
    )
    op.create_index(
        "ix_integration_pushes_workspace_id",
        "integration_pushes",
        ["workspace_id"],
    )

    op.create_table(
        "integration_push_tasks",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("push_id", sa.UUID(), nullable=False),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("external_issue_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["push_id"],
            ["integration_pushes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "push_id",
            "task_ref",
            name="uq_push_task_ref",
        ),
    )
    op.create_index(
        "ix_integration_push_tasks_push_id",
        "integration_push_tasks",
        ["push_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integration_push_tasks_push_id",
        table_name="integration_push_tasks",
    )
    op.drop_table("integration_push_tasks")

    op.drop_index(
        "ix_integration_pushes_workspace_id",
        table_name="integration_pushes",
    )
    op.drop_table("integration_pushes")

    op.drop_index(
        "ix_user_integrations_user_id",
        table_name="user_integrations",
    )
    op.drop_table("user_integrations")

"""Create storyboards table (Phase 20 — T-250).

A Storyboard is a paid, versioned, shareable launch-keynote artifact derived
from a workspace's finalised SPEC / PLAN / HARNESS / TASKS stage versions. It is
not a fifth pipeline stage: each generated version is one row, pinned to the
exact source ``StageVersion`` ids it was built from (``source_stage_version_ids``)
so later workspace edits cannot silently rewrite an existing Storyboard.

Constraints mirror models/storyboard.py one-for-one (same names, predicates) to
keep the ORM and the schema from drifting.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storyboards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("theme", sa.Text(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("speaker_notes_md", sa.Text(), nullable=False),
        sa.Column("demo_script_md", sa.Text(), nullable=False),
        sa.Column("technical_appendix_md", sa.Text(), nullable=False),
        sa.Column("source_map_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_stage_version_ids", postgresql.JSONB(), nullable=False),
        sa.Column("credit_ledger_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("public_share_slug", sa.Text(), nullable=True),
        sa.Column(
            "public_share_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "allow_pdf_download",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "allow_notes_download",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "allow_appendix_download",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "allow_source_layer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        # Workspace/user deletes cascade to their Storyboards.
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
        # NO ACTION (no ondelete) on purpose — the Storyboard directive forbids
        # deleting a referenced credit_ledger entry, so neither SET NULL (as
        # stage.deduction_ledger_id uses) nor RESTRICT is correct here. NO ACTION
        # defers the referential check to end-of-statement, so a user cascade
        # delete that removes both the storyboard and the ledger row in one
        # statement still succeeds, while a stray delete of just the ledger row
        # is rejected.
        sa.ForeignKeyConstraint(
            ["credit_ledger_id"],
            ["credit_ledger.id"],
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_storyboards_workspace_version",
        ),
        sa.CheckConstraint("version > 0", name="ck_storyboards_version"),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed', 'stale')",
            name="ck_storyboards_status",
        ),
        sa.CheckConstraint(
            "char_length(title) <= 200",
            name="ck_storyboards_title_len",
        ),
    )

    # Public share slugs are globally unique when present. NULL slugs (sharing
    # disabled) are excluded via the partial predicate so many Storyboards can
    # coexist unshared.
    op.create_index(
        "uq_storyboards_public_share_slug",
        "storyboards",
        ["public_share_slug"],
        unique=True,
        postgresql_where=sa.text("public_share_slug IS NOT NULL"),
    )

    # List/latest lookups: newest-first per workspace and per user.
    op.create_index(
        "ix_storyboards_workspace_created_at",
        "storyboards",
        ["workspace_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_storyboards_user_created_at",
        "storyboards",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_storyboards_user_created_at", table_name="storyboards")
    op.drop_index("ix_storyboards_workspace_created_at", table_name="storyboards")
    op.drop_index("uq_storyboards_public_share_slug", table_name="storyboards")
    op.drop_table("storyboards")

"""Workspace V1.3 fields.

Adds the four fields required by Phase 14 V1.3 usefulness improvements
(see V1 spec.md §10 / Plan v1.md §18.3 / tasks.md T-160):

- ``template_slug``        — provenance of the starter template the
                             workspace was created from (nullable).
- ``clarification_qa``     — captured Spec Clarification Q&A pairs as
                             JSONB so the spec prompt builder can render
                             them into the user prompt on regenerate.
- ``public_share_slug``    — opaque slug exposed at ``/p/{slug}`` when
                             public sharing is enabled.
- ``public_share_enabled`` — current on/off state of the public share.

A partial unique B-tree index is created on ``public_share_slug`` where
``public_share_enabled = true`` so:

- the hot ``/public/{slug}`` lookup hits a small focused index, and
- multiple workspaces may legitimately carry a NULL or disabled slug
  without colliding on a plain UNIQUE constraint.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("template_slug", sa.Text(), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "clarification_qa",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column("public_share_slug", sa.Text(), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "public_share_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Partial unique index: enforces slug uniqueness only while sharing is
    # active, and accelerates the hot `/public/{slug}` lookup path.
    op.create_index(
        "ix_workspaces_public_share_slug_enabled",
        "workspaces",
        ["public_share_slug"],
        unique=True,
        postgresql_where=sa.text("public_share_enabled = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspaces_public_share_slug_enabled",
        table_name="workspaces",
    )
    op.drop_column("workspaces", "public_share_enabled")
    op.drop_column("workspaces", "public_share_slug")
    op.drop_column("workspaces", "clarification_qa")
    op.drop_column("workspaces", "template_slug")

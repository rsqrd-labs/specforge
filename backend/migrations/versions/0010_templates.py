"""Templates table — system-owned starter templates for Phase 14.

Adds the ``templates`` table that powers the Starter Templates feature
(V1 spec.md §4.11, Plan v1.md §18.3, tasks.md T-160 / T-170).

Design decisions captured here, not in autogenerate:

- The table has no ``user_id`` foreign key. Templates are system-owned
  in V1 — only the seed script (run from a privileged container
  entrypoint) writes to it. User-authored templates are explicitly V2
  (see Spec §14).
- ``slug`` is the natural key referenced by ``Workspace.template_slug``
  for provenance. It is declared UNIQUE so the seed script's
  ``INSERT ... ON CONFLICT (slug) DO UPDATE`` is idempotent.
- ``active`` allows soft-disabling a template via SQL without breaking
  existing workspaces that still reference its slug. The
  ``ix_templates_active_sort`` index covers the only read query the
  endpoint runs (``WHERE active = true ORDER BY sort_order``).

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=False),
        sa.Column("suggested_provider", sa.Text(), nullable=True),
        sa.Column("suggested_model", sa.Text(), nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_templates_slug"),
        sa.CheckConstraint(
            "category IN ('auth', 'payments', 'content', 'realtime', 'agent', 'tooling')",
            name="ck_templates_category",
        ),
    )
    op.create_index(
        "ix_templates_active_sort",
        "templates",
        ["active", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_templates_active_sort", table_name="templates")
    op.drop_table("templates")

"""Workspace Demo Day mode columns.

Demo Day mode is a generation *profile* on top of the four-stage pipeline
(see docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md, Phase 0). It is workspace-scoped
and chosen at creation, mirroring the existing ``disable_critic`` /
``brave_research_enabled`` boolean-column pattern.

- ``mode`` — ``'standard'`` (default) or ``'demo_day'``. NOT NULL with a server
  default of ``'standard'`` so every existing row backfills to standard without a
  data migration (the §4 regression-pin contract: existing workspaces are
  byte-identical to today).
- ``target_agent`` — ``'claude_code'`` or ``'codex'`` (nullable; only set for
  demo_day workspaces). Selects the operating-manual filename/idiom.
- ``time_budget_minutes`` — advisory build-time target (nullable; the linter
  falls back to 300 when NULL).

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column("target_agent", sa.Text(), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("time_budget_minutes", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_workspaces_mode",
        "workspaces",
        "mode IN ('standard', 'demo_day')",
    )
    op.create_check_constraint(
        "ck_workspaces_target_agent",
        "workspaces",
        "target_agent IS NULL OR target_agent IN ('claude_code', 'codex')",
    )
    op.create_check_constraint(
        "ck_workspaces_time_budget_minutes",
        "workspaces",
        "time_budget_minutes IS NULL OR time_budget_minutes > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspaces_time_budget_minutes", "workspaces")
    op.drop_constraint("ck_workspaces_target_agent", "workspaces")
    op.drop_constraint("ck_workspaces_mode", "workspaces")
    op.drop_column("workspaces", "time_budget_minutes")
    op.drop_column("workspaces", "target_agent")
    op.drop_column("workspaces", "mode")

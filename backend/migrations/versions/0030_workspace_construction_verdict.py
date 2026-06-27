"""Workspace construction verdict column (Demo Day mode, Phase 3).

The construction verifier (``demo_day_plan_linter``) certifies that a Demo Day
package is internally consistent (every task maps to a test, every AC maps to a
test, the task DAG is acyclic, a reachable e2e smoke test exists). Its verdict is
inherently *workspace-level* — it spans all four stage versions — so a nullable
JSONB column on ``workspaces`` matches the granularity directly with one small
migration (plan §7.2, the confirmed default in §11.3).

- ``construction_verdict`` — nullable JSONB. NULL until the verifier first runs
  (after the tasks stage exists for a demo_day workspace). The verdict overwrites
  on a staleness re-run; the per-stage versions it stamps inside the JSON
  (``stage_versions``) carry the audit/staleness signal, so no extra columns are
  needed. NULL for every standard workspace (the §4 byte-identical contract:
  standard rows are unchanged and serialise ``construction_verdict: null``).

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "construction_verdict",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "construction_verdict")

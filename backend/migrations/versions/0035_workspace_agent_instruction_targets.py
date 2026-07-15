"""Allow workspaces to export instructions for both supported coding agents.

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_workspaces_target_agent", "workspaces", type_="check")
    op.create_check_constraint(
        "ck_workspaces_target_agent",
        "workspaces",
        "target_agent IS NULL OR target_agent IN ('claude_code', 'codex', 'both')",
    )


def downgrade() -> None:
    # Refuse to silently narrow live rows. Operators must change 'both' rows first.
    connection = op.get_bind()
    if connection.exec_driver_sql(
        "SELECT 1 FROM workspaces WHERE target_agent = 'both' LIMIT 1"
    ).first():
        raise RuntimeError(
            "cannot downgrade while workspaces.target_agent='both' exists"
        )
    op.drop_constraint("ck_workspaces_target_agent", "workspaces", type_="check")
    op.create_check_constraint(
        "ck_workspaces_target_agent",
        "workspaces",
        "target_agent IS NULL OR target_agent IN ('claude_code', 'codex')",
    )

"""GitHub installation pr_check_mode setting.

Issue #27 Phase 4. Per-installation control over the PR-diff acceptance-criteria
judge: ``off`` (never judge), ``manual`` (judge only on an explicit GitHub
re-run), ``auto`` (judge on every routed push — the pre-Phase-4 behaviour).

NOT NULL with a server default of ``'manual'`` so every existing installation
backfills to **manual** — the issue's "PR-diff judging opt-in / manual by
default" intent. This is a deliberate behaviour change on upgrade: installations
that were auto-judging every push stop doing so until a re-run (or until the mode
is flipped to ``auto``), which is the cost cut the issue asks for. A CHECK
constraint pins the value to the three-mode vocabulary at the DB layer.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "github_installations",
        sa.Column(
            "pr_check_mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.create_check_constraint(
        "ck_github_installation_pr_check_mode",
        "github_installations",
        "pr_check_mode IN ('off', 'manual', 'auto')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_github_installation_pr_check_mode",
        "github_installations",
        type_="check",
    )
    op.drop_column("github_installations", "pr_check_mode")

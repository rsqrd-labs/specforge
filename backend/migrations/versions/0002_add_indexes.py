"""Add missing indexes for foreign keys and common query columns.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-02 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])
    op.create_index("ix_stages_workspace_id", "stages", ["workspace_id"])
    op.create_index("ix_stage_versions_stage_id", "stage_versions", ["stage_id"])
    op.create_index("ix_workspaces_user_id", "workspaces", ["user_id"])
    op.create_index(
        "ix_eval_results_stage_version_id", "eval_results", ["stage_version_id"]
    )
    op.create_index("ix_stages_status", "stages", ["status"])
    op.create_index("ix_stages_updated_at", "stages", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_stages_updated_at", table_name="stages")
    op.drop_index("ix_stages_status", table_name="stages")
    op.drop_index("ix_eval_results_stage_version_id", table_name="eval_results")
    op.drop_index("ix_workspaces_user_id", table_name="workspaces")
    op.drop_index("ix_stage_versions_stage_id", table_name="stage_versions")
    op.drop_index("ix_stages_workspace_id", table_name="stages")
    op.drop_index("ix_credit_ledger_user_id", table_name="credit_ledger")

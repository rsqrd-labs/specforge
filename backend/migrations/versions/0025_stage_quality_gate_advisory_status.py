"""Allow the 'advisory' quality-gate status.

The LLM critic gate is now advisory (issue #34): instead of blocking a stage
after its one regenerate, its remaining findings are attached to a delivered,
finalisable draft as non-blocking suggestions. That needs a fourth allowed
value on stages.quality_gate_status.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_stages_quality_gate_status", "stages", type_="check")
    op.create_check_constraint(
        "ck_stages_quality_gate_status",
        "stages",
        "quality_gate_status IN ('clear', 'blocked', 'overridden', 'advisory')",
    )


def downgrade() -> None:
    # Any 'advisory' rows must collapse to 'clear' before the old constraint can
    # be re-applied — an advisory draft is a delivered, finalisable draft, so
    # 'clear' is the correct lossless target.
    op.execute(
        "UPDATE stages SET quality_gate_status = 'clear' "
        "WHERE quality_gate_status = 'advisory'"
    )
    op.drop_constraint("ck_stages_quality_gate_status", "stages", type_="check")
    op.create_check_constraint(
        "ck_stages_quality_gate_status",
        "stages",
        "quality_gate_status IN ('clear', 'blocked', 'overridden')",
    )

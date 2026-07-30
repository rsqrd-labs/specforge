"""Chunk-level generation resume: chunk_plan, resume_source_run_id, 'resume' action.

Before this, a stage generation that completed 3 of 4 chunks and then hit the
provider call cap on the last one threw away all three: the run terminalised,
the credit was refunded, and Regenerate minted a fresh run that re-generated
every chunk from scratch (checkpoints are keyed by ``generation_run_id`` and
were never read across runs). The completed work was durable in
``stage_generation_chunks`` the whole time — nothing read it.

``chunk_plan`` records the ordered chunk keys a run set out to produce, so the
terminal path can name exactly which sections are missing without re-deriving
the chunk plan from the workspace mode, and so a resume can detect that the
chunking changed under it and decline rather than stitch incompatible halves.
``resume_source_run_id`` is the audit link from a resume run to the run whose
checkpoints seeded it.

Both columns are additive and nullable, so pre-existing rows (which are all
terminal) read back as "not resumable" and behave exactly as before.

Revision ID: 0043
Revises: 0042
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stage_generation_runs",
        sa.Column("chunk_plan", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "stage_generation_runs",
        sa.Column("resume_source_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_stage_generation_runs_resume_source",
        "stage_generation_runs",
        "stage_generation_runs",
        ["resume_source_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Widen the action vocabulary to admit the new free, chunk-level retry.
    op.drop_constraint(
        "ck_stage_generation_runs_action", "stage_generation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_stage_generation_runs_action",
        "stage_generation_runs",
        "action IN ('generate', 'regenerate', 'resume')",
    )


def downgrade() -> None:
    # A resume run cannot survive the narrowed constraint. It is a completed
    # attempt like any other, so it is relabelled 'regenerate' (its nearest
    # legacy equivalent) rather than deleted — deleting it would cascade its
    # chunk checkpoints and lose delivered artifact history.
    op.execute(
        "UPDATE stage_generation_runs SET action = 'regenerate' "
        "WHERE action = 'resume'"
    )
    op.drop_constraint(
        "ck_stage_generation_runs_action", "stage_generation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_stage_generation_runs_action",
        "stage_generation_runs",
        "action IN ('generate', 'regenerate')",
    )
    op.drop_constraint(
        "fk_stage_generation_runs_resume_source",
        "stage_generation_runs",
        type_="foreignkey",
    )
    op.drop_column("stage_generation_runs", "resume_source_run_id")
    op.drop_column("stage_generation_runs", "chunk_plan")

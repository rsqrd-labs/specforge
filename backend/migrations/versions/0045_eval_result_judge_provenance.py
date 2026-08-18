"""EvalResult judge provenance (``judge_provider`` / ``judge_model``).

Scores produced by different judge models are not comparable, and the judge
model moves with ``LLM_PROVIDER_PRIORITY`` — the openrouter cutover (issue #152)
relocates the eval judge, critic, Rung-2 compressor and pr_check evaluator all
at once. Without recording which judge scored a row, an ``overall_score`` trend
silently splices two graders at whatever commit the provider flipped, and the
judge-agreement gate in ``docs/evals/ROUTE_PROMOTION.md`` has nothing to join on.

Both columns are **nullable with no backfill**, deliberately. Every pre-existing
row was scored by the Anthropic judge, but that fact was never recorded on the
row; writing it in retroactively would manufacture provenance rather than
preserve it. NULL reads as "scored before provenance was tracked", which is
exactly true.

Additive and index-free: no lock beyond the brief ``ALTER TABLE`` on
``eval_results``.

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_results",
        sa.Column("judge_provider", sa.Text(), nullable=True),
    )
    op.add_column(
        "eval_results",
        sa.Column("judge_model", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_results", "judge_model")
    op.drop_column("eval_results", "judge_provider")

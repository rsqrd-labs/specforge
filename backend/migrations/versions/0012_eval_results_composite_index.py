"""Add composite index on eval_results(stage_version_id, created_at DESC).

The eval polling query — ``SELECT … FROM eval_results WHERE stage_version_id = $1
ORDER BY created_at DESC LIMIT 1`` — hot-paths this table on every stage poll.
The existing single-column ``ix_eval_results_stage_version_id`` narrows to a
stage version but leaves PostgreSQL to sort an unbounded window of rows.  The
composite index with ``created_at DESC`` allows the planner to serve the
``ORDER BY … LIMIT 1`` via an index-only scan (B-tree prefix seek) rather than
a sort.  EI-1 — T-213.

Note on CREATE INDEX CONCURRENTLY: Alembic's standard ``create_index()`` issues
``CREATE INDEX``, which takes a ``ShareLock`` on the table for the full build
duration.  For a table with millions of rows on a live database, prefer running
the index build outside of a transaction::

    CREATE INDEX CONCURRENTLY ix_eval_results_stage_version_created_at
        ON eval_results USING btree (stage_version_id, created_at DESC);

In that case skip this migration and update the ``down_revision`` chain
accordingly.  For fresh databases and small staging tables the non-concurrent
path (this migration) is safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_eval_results_stage_version_created_at",
        "eval_results",
        ["stage_version_id", sa.text("created_at DESC")],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eval_results_stage_version_created_at",
        table_name="eval_results",
        if_exists=True,
    )

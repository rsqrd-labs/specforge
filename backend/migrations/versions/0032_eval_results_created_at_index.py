"""Plain btree index on eval_results(created_at) for the Tier-1 TTL purge (#43).

The retention purge (``services.retention.purge_eval_results``) deletes
``eval_results`` rows older than the TTL window with::

    SELECT id FROM eval_results WHERE created_at < :cutoff LIMIT :batch

The only existing index on the table is the composite
``ix_eval_results_stage_version_created_at (stage_version_id, created_at DESC)``
(migration 0012), whose leading column is ``stage_version_id`` — so a bare
``created_at < cutoff`` predicate cannot use it and would seq-scan the table as
it grows. A plain btree on ``created_at`` answers the purge predicate directly
(``llm_cost_events.created_at`` already has such an index via ``index=True`` on
the model, so only ``eval_results`` needs one here — plan §1.4).

This is additive: the composite index is KEPT (it still serves the per-version
eval poll). The plain index only optimises the retention sweep.

Note on CREATE INDEX CONCURRENTLY (mirrors 0012's convention): Alembic's
``create_index()`` issues ``CREATE INDEX``, which takes a ``ShareLock`` on the
table for the build. For a very large live ``eval_results`` prefer building it
out of band and stamping this revision::

    CREATE INDEX CONCURRENTLY ix_eval_results_created_at
        ON eval_results USING btree (created_at);
    -- then: alembic stamp 0032

For fresh/staging databases the non-concurrent path (this migration) is safe.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_eval_results_created_at"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "eval_results",
        ["created_at"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="eval_results", if_exists=True)

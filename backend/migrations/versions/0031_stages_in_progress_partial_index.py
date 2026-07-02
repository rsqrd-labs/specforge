"""Partial index on stages(updated_at) WHERE status='in_progress' (audit P2).

The stuck-stage recovery sweep (``recovery_service.recover_stuck_stages``) runs
every 60s and queries:

    SELECT ... FROM stages WHERE status = 'in_progress' AND updated_at < :cutoff

``in_progress`` rows are rare and short-lived (a stage only sits there while a
generation streams), but the existing full ``ix_stages_status`` indexes *every*
row's status — most of which are ``finalised`` / ``draft`` — so as ``stages``
grows the planner scans far more than the handful of live generations. A PARTIAL
index covering only ``in_progress`` rows, keyed by ``updated_at``, is tiny
(bounded by concurrent generations, not table size) and answers the sweep's
``status = 'in_progress' AND updated_at < cutoff`` predicate directly (audit §5).

This is additive: ``ix_stages_status`` is KEPT — it still serves the other status
filters (e.g. the ``status = 'finalised'`` reads). The partial index only
optimises the recovery sweep.

Postgres-only (partial indexes via ``postgresql_where``); a non-postgres
(e.g. sqlite test) backend skips it cleanly.

Deploy note: plain ``CREATE INDEX`` takes a brief write-blocking ``SHARE`` lock
for the build (matching migration 0002's convention). On a very large ``stages``
table an operator may prefer to build it out-of-band with
``CREATE INDEX CONCURRENTLY ix_stages_in_progress_updated_at ON stages
(updated_at) WHERE status = 'in_progress';`` and then ``alembic stamp 0031`` —
the index is small here (partial on a rare status) so the inline build is cheap.

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_stages_in_progress_updated_at"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # Partial indexes are a no-op enhancement on non-postgres test backends.
        return
    op.create_index(
        _INDEX_NAME,
        "stages",
        ["updated_at"],
        postgresql_where=sa.text("status = 'in_progress'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index(_INDEX_NAME, table_name="stages")

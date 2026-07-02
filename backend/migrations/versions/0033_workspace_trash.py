"""Workspace trash lifecycle: archived_at + retention_ack_version (#43, Phase 3).

Adds the two columns the Tier-3 workspace-trash purge predicate keys on
(``services.retention.purge_trashed_workspaces``), plus a partial index matching
that predicate exactly (the 0031 pattern):

  - ``archived_at TIMESTAMPTZ NULL`` — the purge clock. Set to now() by the delete
    (archive) flow, cleared on restore. **Backfilled to deploy time (now()) for
    existing archived rows**, because ``workspaces.updated_at`` has no ``onupdate``
    and so cannot date the original archive (plan §1.5/§5.1). This means nothing
    already archived is instantly eligible — the clock starts at deploy.
  - ``retention_ack_version TEXT NULL`` — the policy-version string the delete
    dialog displayed, stamped by the DELETE handler when the client supplies it.
    Presence ⇒ the short acked window; NULL (legacy / stale-SPA delete) ⇒ the
    conservative legacy window (plan §5.2).

The partial index ``ix_workspaces_archived_at ON workspaces (archived_at) WHERE
status = 'archived'`` answers the purge sweep's ``status='archived' AND
archived_at < cutoff`` predicate directly and stays tiny (archived rows only).

Postgres-only for the partial index (like 0031); the columns are added on every
dialect so the sqlite unit backend still has them.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_workspaces_archived_at"


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("retention_ack_version", sa.Text(), nullable=True),
    )
    # Backfill existing archived rows to deploy time so the trash clock starts now
    # (updated_at is unreliable — no onupdate). Active rows stay NULL.
    op.execute(
        sa.text(
            "UPDATE workspaces SET archived_at = now() "
            "WHERE status = 'archived' AND archived_at IS NULL"
        )
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            _INDEX_NAME,
            "workspaces",
            ["archived_at"],
            postgresql_where=sa.text("status = 'archived'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index(_INDEX_NAME, table_name="workspaces", if_exists=True)
    op.drop_column("workspaces", "retention_ack_version")
    op.drop_column("workspaces", "archived_at")

"""GitHub living system of record — schema (Phase 21 — T-265).

Turns the one-shot Phase 13 export into a living, bidirectional integration.
This migration **creates two new tables and ALTERs two existing ones** — it must
not recreate ``integration_pushes`` / ``integration_push_tasks`` (those came from
``0007_github_integration.py``). Column names match ``V1 spec.md`` v2.0.0 §10.

New tables:
- ``github_installations``  — one row per GitHub App installation (identity).
- ``github_webhook_events`` — inbound-delivery idempotency/dedup, mirroring
  ``stripe_webhook_events``.

Altered tables:
- ``integration_pushes``     — rekeyed from (workspace, provider) onto the
  immutable ``repo_id``; gains App/sync/PR/increment fields.
- ``integration_push_tasks`` — gains bidirectional sync state.

The one-active-push-per-provider unique constraint is replaced with a partial
unique index enforcing **one live push per repo**: ``(workspace_id, repo_id)
WHERE status <> 'failed'``. The status enum is exactly
``pending`` / ``completed`` / ``failed`` / ``stale`` (spec §10) — there is **no
``'active'`` literal**; a "live" push is the single non-``failed`` row, which is
what the predicate keys on. ``repo_id`` is nullable on purpose: legacy Phase-13
pushes have none, Postgres treats nulls as distinct so the partial index
tolerates them, and the value is backfilled lazily on the next App export (T-269).

The ``increment_id`` FK targets (``increments.id``) are deferred to ``0017``
(T-278) so this migration does not depend on the increments tables.

Constraints/indexes mirror models/integration_push.py and
models/integration_push_task.py one-for-one to keep the ORM and schema in sync.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- new tables ---------------------------------------------------------
    op.create_table(
        "github_installations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # GitHub's numeric installation id (not the App id).
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.Text(), nullable=False),
        # User | Organization
        sa.Column("account_type", sa.Text(), nullable=False),
        # all | selected
        sa.Column("repository_selection", sa.Text(), nullable=False),
        # The Thought2Build user who installed, if known via identity OAuth. SET NULL
        # on user delete: the installation outlives the user account that linked it.
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "suspended_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "installation_id",
            name="uq_github_installation_installation_id",
        ),
    )

    op.create_table(
        "github_webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # The X-GitHub-Delivery header. UNIQUE serialises duplicate deliveries:
        # the first insert wins, the second raises IntegrityError the handler
        # catches and skips — every webhook handler is idempotent.
        sa.Column("delivery_id", sa.Text(), nullable=False),
        # e.g. issues | pull_request | installation
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Set when the worker finishes reconciliation.
        sa.Column(
            "processed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "delivery_id",
            name="uq_github_webhook_event_delivery_id",
        ),
    )

    # --- alter integration_pushes (exists since 0007) -----------------------
    op.add_column(
        "integration_pushes",
        sa.Column(
            "installation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("github_installations.id"),
            nullable=True,
        ),
    )
    # Immutable GitHub repository id — the reconciliation key. Nullable: legacy
    # Phase-13 pushes have none; backfilled lazily on next App export (T-269).
    op.add_column(
        "integration_pushes",
        sa.Column("repo_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "integration_pushes",
        sa.Column(
            "export_mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'files_to_default'"),
        ),
    )
    op.add_column(
        "integration_pushes",
        sa.Column("branch_name", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_pushes",
        sa.Column("pr_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "integration_pushes",
        sa.Column(
            "source_stage_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stage_versions.id"),
            nullable=True,
        ),
    )
    # FK target (increments.id) added in 0017 (T-278).
    op.add_column(
        "integration_pushes",
        sa.Column("increment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Replace one-active-push-per-provider with one-LIVE-push-per-repo. The enum
    # has no 'active' literal: a live push is the single non-'failed' row, so the
    # predicate is exactly `status <> 'failed'`. NULL repo_id (legacy rows) are
    # distinct under Postgres, so the partial index tolerates them.
    op.drop_constraint(
        "uq_integration_push_workspace_provider",
        "integration_pushes",
        type_="unique",
    )
    op.create_index(
        "uq_integration_push_workspace_repo_active",
        "integration_pushes",
        ["workspace_id", "repo_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'failed'"),
    )
    op.create_index(
        "ix_integration_pushes_repo_id",
        "integration_pushes",
        ["repo_id"],
    )

    # --- alter integration_push_tasks (exists since 0007) -------------------
    # FK target (increments.id) added in 0017 (T-278).
    op.add_column(
        "integration_push_tasks",
        sa.Column("increment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "integration_push_tasks",
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
    )
    op.add_column(
        "integration_push_tasks",
        sa.Column(
            "done_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    # pr_merge | manual
    op.add_column(
        "integration_push_tasks",
        sa.Column("done_via", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_push_tasks",
        sa.Column(
            "synced_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_integration_push_tasks_issue_number",
        "integration_push_tasks",
        ["external_issue_number"],
    )


def downgrade() -> None:
    # Reverse integration_push_tasks alterations.
    op.drop_index(
        "ix_integration_push_tasks_issue_number",
        table_name="integration_push_tasks",
    )
    op.drop_column("integration_push_tasks", "synced_at")
    op.drop_column("integration_push_tasks", "done_via")
    op.drop_column("integration_push_tasks", "done_at")
    op.drop_column("integration_push_tasks", "state")
    op.drop_column("integration_push_tasks", "increment_id")

    # Reverse integration_pushes alterations. Drop the partial unique index
    # (it references repo_id) before dropping the column, and restore the legacy
    # (workspace_id, provider) unique constraint last.
    op.drop_index("ix_integration_pushes_repo_id", table_name="integration_pushes")
    op.drop_index(
        "uq_integration_push_workspace_repo_active",
        table_name="integration_pushes",
    )
    op.create_unique_constraint(
        "uq_integration_push_workspace_provider",
        "integration_pushes",
        ["workspace_id", "provider"],
    )
    op.drop_column("integration_pushes", "increment_id")
    op.drop_column("integration_pushes", "source_stage_version_id")
    op.drop_column("integration_pushes", "pr_number")
    op.drop_column("integration_pushes", "branch_name")
    op.drop_column("integration_pushes", "export_mode")
    op.drop_column("integration_pushes", "repo_id")
    op.drop_column("integration_pushes", "installation_id")

    # Drop the new tables.
    op.drop_table("github_webhook_events")
    op.drop_table("github_installations")

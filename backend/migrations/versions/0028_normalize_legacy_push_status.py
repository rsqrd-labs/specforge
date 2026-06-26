"""Normalize legacy integration_pushes.status values to the canonical vocabulary.

GitHub integration audit #4. The ``IntegrationPush`` ORM and the Phase-21 App
path use a single status vocabulary — ``pending`` / ``completed`` / ``failed`` /
``stale`` — but the retained Phase-13 synchronous export path historically wrote
``in_progress`` / ``success`` / ``error``. Those legacy words break two invariants:

  * ``find_live_push`` keys on ``status <> 'failed'``, so a legacy ``error`` push
    was wrongly treated as **live**, pinning the repo slot against re-export;
  * ``reconcile_drift`` only backfills ``status = 'completed'``, so a legacy
    ``success`` push was never drift-reconciled;
  * and ``IntegrationPushRead`` (now strict canonical) would 500 on either.

The legacy code paths are converged to the canonical words in the same change, so
this migration is a one-time backfill that maps any rows still on the legacy
vocabulary onto the canonical equivalents. Idempotent: a second run touches
nothing (no legacy values remain).

``downgrade`` is intentionally a no-op: the reverse mapping is ambiguous —
``completed`` is produced by *both* the App path and (now) the legacy path, so it
cannot be safely demoted back to ``success`` for only the legacy rows. The
vocabulary is unified going forward.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (legacy value, canonical value) — applied in one statement each so the partial
# unique index (``status <> 'failed'``) sees a consistent state at every step.
_STATUS_REMAP: tuple[tuple[str, str], ...] = (
    ("in_progress", "pending"),
    ("success", "completed"),
    ("error", "failed"),
)


def upgrade() -> None:
    for legacy, canonical in _STATUS_REMAP:
        op.execute(
            "UPDATE integration_pushes "
            f"SET status = '{canonical}' WHERE status = '{legacy}'"
        )


def downgrade() -> None:
    # No-op: the canonical → legacy mapping is ambiguous (see module docstring).
    pass

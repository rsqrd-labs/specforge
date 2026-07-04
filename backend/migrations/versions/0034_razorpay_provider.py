"""Widen billing provider CHECKs for Razorpay + seed its reconcile cursor (#44).

Step 2 of the Razorpay integration (``docs/RAZORPAY_INTEGRATION_PLAN.md`` §3).
Additive only — no new tables (the Phase-22 billing schema is already
provider-neutral and keys everything by ``(provider, provider_order_id)``):

1. The five neutral billing tables' ``provider`` CHECKs widen to
   ``('lemonsqueezy','stripe','razorpay')``. Migration 0018 declared these CHECKs
   inline, so a migrated database carries the Postgres auto-generated names
   (``<table>_provider_check``) while the ORM models declare ``ck_*_provider`` —
   both candidates are dropped (``IF EXISTS``) and the replacement is added under
   the canonical ``ck_*_provider`` name, converging the two schema-creation paths.
2. ``billing_reconciliation_cursors``'s CHECK widens to
   ``('lemonsqueezy','razorpay')`` — reconcile lane 2 pages each configured
   provider from its own cursor row. Stripe stays excluded: it never reconciles
   (T-308 decommission), exactly as before.
3. The ``('razorpay')`` cursor row is seeded idempotently
   (``ON CONFLICT DO NOTHING``), mirroring 0018's lemonsqueezy seed.

Existing partial-unique idempotency indexes
(``uq_billing_credit_packs_provider_order`` etc.) already key by provider — no
index changes. Dropping + re-adding a CHECK takes a brief exclusive lock and one
validation scan; these tables are small (the product is not live), so this is
effectively instant.

Downgrade is guarded: it refuses (raises) while any ``provider='razorpay'`` row
exists in the five tables — narrowing the CHECK over live razorpay money rows
would either fail validation or strand unaccountable history. With no such rows
it deletes the razorpay cursor row and restores the narrow CHECKs (under the
canonical ``ck_*`` names — the auto-generated 0018 names are not resurrected).

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, canonical constraint name) — the five provider-neutral billing tables.
# The reconcile cursor is handled separately (different value set).
_PROVIDER_CHECKS: tuple[tuple[str, str], ...] = (
    ("billing_checkout_attempts", "ck_bca_provider"),
    ("billing_credit_packs", "ck_bcp_provider"),
    ("billing_credit_debts", "ck_bcd_provider"),
    ("billing_admin_corrections", "ck_bac_provider"),
    ("billing_webhook_events", "ck_bwe_provider"),
)

_WIDE = "provider IN ('lemonsqueezy','stripe','razorpay')"
_NARROW = "provider IN ('lemonsqueezy','stripe')"
_CURSOR_WIDE = "provider IN ('lemonsqueezy','razorpay')"
_CURSOR_NARROW = "provider IN ('lemonsqueezy')"


def _replace_provider_check(table: str, name: str, definition: str) -> None:
    """Swap a table's provider CHECK, whichever of the two known names it has."""
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_provider_check")
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({definition})")


def upgrade() -> None:
    for table, name in _PROVIDER_CHECKS:
        _replace_provider_check(table, name, _WIDE)

    _replace_provider_check(
        "billing_reconciliation_cursors", "ck_brc_provider", _CURSOR_WIDE
    )
    op.execute(
        "INSERT INTO billing_reconciliation_cursors(provider) VALUES ('razorpay') "
        "ON CONFLICT (provider) DO NOTHING"
    )


def downgrade() -> None:
    # Refuse to narrow the CHECKs over live razorpay rows: money history must
    # never be stranded outside its own CHECK (and ADD CONSTRAINT would fail
    # validation anyway). Settle or migrate those rows first.
    bind = op.get_bind()
    offending: list[str] = []
    for table, _ in _PROVIDER_CHECKS:
        exists = bind.execute(
            sa.text(
                f"SELECT EXISTS (SELECT 1 FROM {table} WHERE provider = 'razorpay')"
            )
        ).scalar_one()
        if exists:
            offending.append(table)
    if offending:
        raise RuntimeError(
            "Cannot downgrade 0034: provider='razorpay' rows exist in "
            f"{', '.join(offending)}. Settle/remove them before narrowing the "
            "provider CHECKs."
        )

    # Cursor row must go before its CHECK narrows, or the re-add fails validation.
    op.execute("DELETE FROM billing_reconciliation_cursors WHERE provider = 'razorpay'")
    _replace_provider_check(
        "billing_reconciliation_cursors", "ck_brc_provider", _CURSOR_NARROW
    )

    for table, name in _PROVIDER_CHECKS:
        _replace_provider_check(table, name, _NARROW)

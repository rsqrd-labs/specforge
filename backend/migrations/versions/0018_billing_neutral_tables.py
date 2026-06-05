"""Provider-neutral billing tables + idempotent Stripe backfill (Phase 22 — T-290).

Lands the provider-neutral billing schema that replaces Stripe-specific tables at
runtime (``V1 spec.md`` §9-12, ``Plan v1.md`` §25.6). Six new tables, three
``credit_ledger`` reason-uniqueness indexes (the second idempotency barrier), and a
balance-preserving, idempotent backfill of every ``stripe_credit_packs`` row into
``billing_credit_packs``.

New tables (money columns are INTEGER cents; all timestamps TIMESTAMPTZ):
- ``billing_checkout_attempts``      — one row per checkout intent; stores only the
  ``checkout_nonce_hash`` (sha256), never a raw nonce. ``checkout_ref`` is the
  client polling key. The webhook is the sole grant authority.
- ``billing_credit_packs``           — the neutral credit-pack ledger with the full
  lifetime accounting set (consumed/expired/debt_recovered/revoked) driving FIFO
  drain, lazy expiry, debt recovery, and exactly-once proportional reversals.
- ``billing_credit_debts``           — recoverable negative balance from a reversed
  pack; one debt per source pack (``source_pack_id`` ON DELETE RESTRICT so debt is
  never silently lost).
- ``billing_admin_corrections``      — append-only, evidence-backed manual grants;
  unique on ``(provider, provider_order_id)``; user FKs ON DELETE RESTRICT.
- ``billing_webhook_events``         — the durable, sanitised inbox; 4-part identity
  uniqueness ``(provider, event_name, provider_object_id, payload_hash)`` and a
  ``normalized_payload`` JSONB (no raw provider body).
- ``billing_reconciliation_cursors`` — authoritative reconcile state (not Redis);
  ``lemonsqueezy``-only (it never holds a ``stripe`` row).

The ``provider`` CHECK on every table allows both ``'lemonsqueezy'`` and ``'stripe'``
(the backfill inserts ``provider='stripe'`` rows) — **except** the reconciliation
cursor, which is ``lemonsqueezy``-only.

Backfill (idempotent, balance-preserving):
- ``INSERT … SELECT … ON CONFLICT (provider, provider_checkout_id)
  WHERE provider_checkout_id IS NOT NULL DO NOTHING`` so a partially-applied
  migration is re-runnable.
- Never modifies ``users.credit_balance`` (this is an audit copy that preserves
  balances exactly) and never infers historical Stripe dispute revoke amounts from
  ``credits_remaining`` (current Stripe dispute handling zeroes ``credits_remaining``
  even when the effective revoke was smaller → ``credits_revoked=0`` for **every**
  backfilled row, including disputed ones). Neutral ``credits_revoked`` is
  authoritative only for reversals processed after this migration.

Retention: ``billing_webhook_events`` and terminal ``billing_checkout_attempts`` are
bounded by the daily ``purge_billing_events`` job (T-298), not pruned here.

The Stripe tables (``stripe_credit_packs`` / ``stripe_webhook_events``) are
**retained** (audit + the 7-day webhook grace path) and survive a downgrade.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # billing_checkout_attempts
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE billing_checkout_attempts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            checkout_ref TEXT NOT NULL UNIQUE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL CHECK (provider IN ('lemonsqueezy','stripe')),
            provider_checkout_id TEXT NULL,
            checkout_nonce_hash TEXT NOT NULL,
            credits INTEGER NOT NULL CHECK (credits > 0),
            price_cents INTEGER NOT NULL CHECK (price_cents > 0),
            currency TEXT NOT NULL,
            validity_days INTEGER NOT NULL CHECK (validity_days > 0),
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN
                    ('created','provider_created','completed','expired','failed')),
            provider_order_id TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NULL,
            success_redirect_seen_at TIMESTAMPTZ NULL
        )
        """)
    op.execute("""
        CREATE INDEX ix_billing_checkout_attempts_user_created
            ON billing_checkout_attempts(user_id, created_at DESC)
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_checkout_attempts_provider_checkout
            ON billing_checkout_attempts(provider, provider_checkout_id)
            WHERE provider_checkout_id IS NOT NULL
        """)

    # -----------------------------------------------------------------------
    # billing_credit_packs
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE billing_credit_packs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL CHECK (provider IN ('lemonsqueezy','stripe')),
            provider_checkout_id TEXT NULL,
            provider_order_id TEXT NULL,
            provider_customer_id TEXT NULL,
            provider_variant_id TEXT NULL,
            credits_purchased INTEGER NOT NULL CHECK (credits_purchased > 0),
            credits_remaining INTEGER NOT NULL CHECK (credits_remaining >= 0),
            credits_consumed INTEGER NOT NULL DEFAULT 0 CHECK (credits_consumed >= 0),
            credits_expired INTEGER NOT NULL DEFAULT 0 CHECK (credits_expired >= 0),
            credits_debt_recovered INTEGER NOT NULL DEFAULT 0
                CHECK (credits_debt_recovered >= 0),
            credits_revoked INTEGER NOT NULL DEFAULT 0 CHECK (credits_revoked >= 0),
            price_cents INTEGER NOT NULL CHECK (price_cents > 0),
            currency TEXT NOT NULL,
            paid_item_amount_cents INTEGER NOT NULL CHECK (paid_item_amount_cents > 0),
            provider_order_total_cents INTEGER NULL
                CHECK (provider_order_total_cents IS NULL
                    OR provider_order_total_cents >= 0),
            provider_refunded_total_cents_seen INTEGER NOT NULL DEFAULT 0
                CHECK (provider_refunded_total_cents_seen >= 0),
            refunded_item_amount_cents_processed INTEGER NOT NULL DEFAULT 0
                CHECK (refunded_item_amount_cents_processed >= 0),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','consumed','expired','refunded','disputed')),
            purchased_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_bcp_remaining_leq_purchased
                CHECK (credits_remaining <= credits_purchased),
            CONSTRAINT ck_bcp_accounting_sum CHECK
                (credits_remaining + credits_consumed + credits_expired
                    + credits_debt_recovered <= credits_purchased),
            CONSTRAINT ck_bcp_refunded_item_leq_paid CHECK
                (refunded_item_amount_cents_processed <= paid_item_amount_cents),
            CONSTRAINT ck_bcp_refunded_total_leq_order CHECK
                (provider_order_total_cents IS NULL
                    OR provider_refunded_total_cents_seen
                        <= provider_order_total_cents),
            CONSTRAINT ck_bcp_revoked_leq_purchased
                CHECK (credits_revoked <= credits_purchased)
        )
        """)
    # The provider/order and provider/checkout partial-unique indexes are the
    # primary idempotency barrier for a duplicate order_created — and the
    # provider_checkout one MUST exist before the backfill below (its
    # ON CONFLICT (provider, provider_checkout_id) … inference targets it).
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_credit_packs_provider_order
            ON billing_credit_packs(provider, provider_order_id)
            WHERE provider_order_id IS NOT NULL
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_credit_packs_provider_checkout
            ON billing_credit_packs(provider, provider_checkout_id)
            WHERE provider_checkout_id IS NOT NULL
        """)
    op.execute("""
        CREATE INDEX ix_billing_credit_packs_user_active
            ON billing_credit_packs(user_id, expires_at) WHERE status = 'active'
        """)
    op.execute("""
        CREATE INDEX ix_billing_credit_packs_user_history
            ON billing_credit_packs(user_id, purchased_at DESC)
        """)

    # -----------------------------------------------------------------------
    # billing_credit_debts
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE billing_credit_debts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_pack_id UUID NOT NULL
                REFERENCES billing_credit_packs(id) ON DELETE RESTRICT,
            provider TEXT NOT NULL CHECK (provider IN ('lemonsqueezy','stripe')),
            provider_order_id TEXT NULL,
            credits_owed INTEGER NOT NULL CHECK (credits_owed > 0),
            credits_recovered INTEGER NOT NULL DEFAULT 0 CHECK (credits_recovered >= 0),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','recovered')),
            reason TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_bcd_recovered_leq_owed
                CHECK (credits_recovered <= credits_owed)
        )
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_credit_debts_source_pack
            ON billing_credit_debts(source_pack_id)
        """)
    op.execute("""
        CREATE INDEX ix_billing_credit_debts_user_pending
            ON billing_credit_debts(user_id, created_at) WHERE status = 'pending'
        """)

    # -----------------------------------------------------------------------
    # billing_admin_corrections (append-only — no UPDATE/DELETE application paths)
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE billing_admin_corrections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            target_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            billing_credit_pack_id UUID NULL
                REFERENCES billing_credit_packs(id) ON DELETE RESTRICT,
            provider TEXT NOT NULL CHECK (provider IN ('lemonsqueezy','stripe')),
            provider_order_id TEXT NOT NULL,
            credits INTEGER NOT NULL CHECK (credits > 0),
            price_cents INTEGER NOT NULL CHECK (price_cents > 0),
            currency TEXT NOT NULL,
            reason TEXT NOT NULL,
            evidence_url TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_admin_corrections_provider_order
            ON billing_admin_corrections(provider, provider_order_id)
        """)

    # -----------------------------------------------------------------------
    # billing_webhook_events (durable sanitised inbox)
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE billing_webhook_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider TEXT NOT NULL CHECK (provider IN ('lemonsqueezy','stripe')),
            event_name TEXT NOT NULL,
            provider_object_type TEXT NOT NULL,
            provider_object_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'received'
                CHECK (status IN ('received','processing','processed','failed')),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            last_error TEXT NULL,
            normalized_payload JSONB NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ NULL
        )
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_billing_webhook_events_identity
            ON billing_webhook_events(
                provider, event_name, provider_object_id, payload_hash)
        """)
    op.execute("""
        CREATE INDEX ix_billing_webhook_events_pending
            ON billing_webhook_events(status, received_at)
            WHERE status IN ('received','failed','processing')
        """)

    # -----------------------------------------------------------------------
    # billing_reconciliation_cursors (lemonsqueezy-only)
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE billing_reconciliation_cursors (
            provider TEXT PRIMARY KEY CHECK (provider IN ('lemonsqueezy')),
            last_successful_run_at TIMESTAMPTZ NOT NULL
                DEFAULT '1970-01-01 00:00:00+00',
            last_run_started_at TIMESTAMPTZ NULL,
            last_run_completed_at TIMESTAMPTZ NULL,
            last_error TEXT NULL,
            state JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
    op.execute("""
        INSERT INTO billing_reconciliation_cursors(provider) VALUES ('lemonsqueezy')
            ON CONFLICT (provider) DO NOTHING
        """)

    # -----------------------------------------------------------------------
    # credit_ledger reason-uniqueness indexes (the second idempotency barrier).
    # The pre-existing uq_credit_ledger_refund_reason (0005) is intentionally
    # left in place — refund:billing:% rows match both, by design.
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE UNIQUE INDEX uq_credit_ledger_billing_purchase_reason
            ON credit_ledger(reason) WHERE reason LIKE 'billing_purchase:%'
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_credit_ledger_billing_reversal_reason
            ON credit_ledger(reason)
            WHERE reason LIKE 'refund:billing:%'
                OR reason LIKE 'debt_recovery:billing:%'
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_credit_ledger_admin_billing_correction_reason
            ON credit_ledger(reason) WHERE reason LIKE 'admin_billing_correction:%'
        """)

    # -----------------------------------------------------------------------
    # Idempotent, balance-preserving backfill of stripe_credit_packs.
    #
    # The provider_checkout partial-unique index above is the ON CONFLICT target,
    # so this is safe to re-run on a partially-applied migration. We never touch
    # users.credit_balance and never infer historical dispute revoke amounts from
    # credits_remaining (credits_revoked=0 for every backfilled row, disputed
    # included) — historical Stripe dispute audit stays in the Stripe tables and
    # stripe_dispute:* ledger rows.
    # -----------------------------------------------------------------------
    op.execute("""
        INSERT INTO billing_credit_packs (
            user_id,
            provider,
            provider_checkout_id,
            provider_order_id,
            credits_purchased,
            credits_remaining,
            credits_consumed,
            credits_expired,
            credits_debt_recovered,
            credits_revoked,
            price_cents,
            currency,
            paid_item_amount_cents,
            provider_order_total_cents,
            provider_refunded_total_cents_seen,
            refunded_item_amount_cents_processed,
            status,
            purchased_at,
            expires_at,
            created_at
        )
        SELECT
            user_id,
            'stripe',
            stripe_session_id,
            stripe_payment_intent_id,
            credits_purchased,
            credits_remaining,
            CASE WHEN status IN ('active','consumed')
                 THEN credits_purchased - credits_remaining ELSE 0 END,
            CASE WHEN status = 'expired'
                 THEN credits_purchased - credits_remaining ELSE 0 END,
            0,
            0,
            price_cents,
            'USD',
            price_cents,
            price_cents,
            CASE WHEN status = 'disputed' THEN price_cents ELSE 0 END,
            CASE WHEN status = 'disputed' THEN price_cents ELSE 0 END,
            status,
            purchased_at,
            expires_at,
            created_at
        FROM stripe_credit_packs
        ON CONFLICT (provider, provider_checkout_id)
            WHERE provider_checkout_id IS NOT NULL DO NOTHING
        """)


def downgrade() -> None:
    # Drop the six neutral tables in reverse FK order (children referencing
    # billing_credit_packs / users first), then the credit_ledger reason
    # indexes (those live on credit_ledger, so DROP TABLE won't remove them).
    # The Stripe tables (stripe_credit_packs / stripe_webhook_events) are
    # retained — never dropped here.
    op.execute("DROP TABLE IF EXISTS billing_credit_debts")
    op.execute("DROP TABLE IF EXISTS billing_admin_corrections")
    op.execute("DROP TABLE IF EXISTS billing_webhook_events")
    op.execute("DROP TABLE IF EXISTS billing_reconciliation_cursors")
    op.execute("DROP TABLE IF EXISTS billing_checkout_attempts")
    op.execute("DROP TABLE IF EXISTS billing_credit_packs")

    op.execute("DROP INDEX IF EXISTS uq_credit_ledger_billing_purchase_reason")
    op.execute("DROP INDEX IF EXISTS uq_credit_ledger_billing_reversal_reason")
    op.execute("DROP INDEX IF EXISTS uq_credit_ledger_admin_billing_correction_reason")

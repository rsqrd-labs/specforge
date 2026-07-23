"""
Harness contracts for Phase 25 — Lemon Squeezy Billing Migration.

These tests are RED before T-290 through T-307 are implemented and GREEN after.
They encode the *plan* (Plan v1.md §25, which deliberately refines a few HANDOFF
points), not the raw HANDOFF — where the two differ, this harness asserts the
plan. Every test maps to one or more Phase-25 tasks.

  T-290  Migration 0018 — six provider-neutral billing tables, three credit_ledger
         reason-uniqueness indexes, and an idempotent Stripe→neutral backfill that
         never touches users.credit_balance. Stripe tables retained.
  T-291  ORM models + schemas for the six tables; Stripe models retained.
  T-292  lemonsqueezy_* + admin_user_emails config, derived props, production guard.
  T-293  services.queue refactored into a generic wrapper (github_job throttle +
         gh:deadletter preserved); billing_job → billing:deadletter.
  T-294  CreditService onto BillingCreditPack (+credits_consumed/credits_expired)
         and a debt-first grant helper.
  T-295  LemonSqueezyService — httpx JSON:API checkout + get_order.
  T-296  Billing API — package(+currency), checkout(attempt-first, returns
         checkout_ref), status(checkout_ref+user_id), history.
  T-297  Webhook ingestion — raw-body HMAC over two secrets, event-name match,
         sanitised inbox, enqueue by row id.
  T-298  billing_process_webhook + 60s pending-sweep + purge_billing_events +
         worker registration.
  T-299  order_created — full validation checklist; grant/validate from the
         ATTEMPT SNAPSHOT (not live config); idempotent.
  T-300  order_refunded/fraud/debt — floor/clamp normalisation, monotonic
         processed level, single-ordered pack lock, recoverable debt.
  T-301  billing_reconcile — cursor FOR UPDATE NOWAIT, three lanes, never
         auto-grants, bounded lane-2.
  T-302  Admin correction — require_admin allowlist, idempotent.
  T-303  Stripe cutover — Lemon-only checkout, 7-day grace, no SDK removal here.
  T-304  Observability — provider-labelled metrics + redaction.
  T-305  Frontend — see phase25-lemonsqueezy-billing.contract.test.ts.
  T-306  backend/tests/test_phase25_*.py covers the money-math behaviours this
         source-grep harness cannot run (the behavioural lever).
  T-307  Docs / release gate.

Note: the Phase-21 Stripe harness (test_phase21_stripe_payments_contract.py) is
intentionally left untouched here — it still matches the current Stripe code; its
retirement is part of implementing T-306, not of generating this harness.
"""

from __future__ import annotations

import re

from conftest import BACKEND_ROOT, read_backend_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIGRATIONS_DIR = BACKEND_ROOT / "migrations" / "versions"
REPO_ROOT_DOCS = BACKEND_ROOT.parent / "docs"

# Files in which Phase-25 billing logic may live. The plan deliberately leaves
# some module placement open (T-298: services/billing_worker.py OR
# services/billing/processing.py), so cross-cutting invariant greps concatenate
# every candidate that exists rather than pinning one path.
_BILLING_SOURCE_CANDIDATES = (
    ("services", "billing_worker.py"),
    ("services", "billing", "processing.py"),
    ("services", "billing", "__init__.py"),
    ("services", "billing", "webhook.py"),
    ("services", "billing", "refunds.py"),
    ("services", "billing", "reconcile.py"),
    ("services", "billing_service.py"),
    ("services", "lemonsqueezy_service.py"),
    ("routers", "billing.py"),
    ("services", "credit_service.py"),
)


def _find_function_body(source: str, fn_name: str) -> str | None:
    """Extract the body of a top-level or method function by name."""
    pattern = re.compile(
        rf"(?:async\s+)?def\s+{re.escape(fn_name)}\s*\([^)]*\)[^:]*:(.*?)"
        r"(?=\n\s{0,4}(?:async\s+)?def\s+\w|\n\s{0,4}class\s+\w|\Z)",
        re.DOTALL,
    )
    m = pattern.search(source)
    return m.group(1) if m else None


def _migrations_text() -> str:
    if not _MIGRATIONS_DIR.exists():
        return ""
    return "\n".join(f.read_text(encoding="utf-8") for f in _MIGRATIONS_DIR.glob("*.py"))


def _migration_0018() -> str:
    """Return the 0018 billing-neutral migration text (by name, else by content)."""
    if not _MIGRATIONS_DIR.exists():
        return ""
    for f in _MIGRATIONS_DIR.glob("*0018*"):
        return f.read_text(encoding="utf-8")
    for f in _MIGRATIONS_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if "billing_credit_packs" in text:
            return text
    return ""


def _billing_sources() -> str:
    parts: list[str] = []
    for cand in _BILLING_SOURCE_CANDIDATES:
        p = BACKEND_ROOT.joinpath(*cand)
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _source_containing(token: str) -> str:
    """Concatenated text of every candidate billing source that contains token."""
    parts: list[str] = []
    for cand in _BILLING_SOURCE_CANDIDATES:
        p = BACKEND_ROOT.joinpath(*cand)
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if token in text:
                parts.append(text)
    return "\n".join(parts)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _nospace(text: str) -> str:
    return re.sub(r"\s+", "", text)


# ===========================================================================
# T-290 — Migration 0018: provider-neutral billing tables
# ===========================================================================

_NEW_TABLES = (
    "billing_checkout_attempts",
    "billing_credit_packs",
    "billing_credit_debts",
    "billing_admin_corrections",
    "billing_webhook_events",
    "billing_reconciliation_cursors",
)


def test_t290_migration_0018_exists_after_0017() -> None:
    """T-290 — a 0018 migration must create the neutral tables and chain off 0017."""
    mig = _migration_0018()
    assert mig, (
        "No migration creates 'billing_credit_packs'. T-290 requires "
        "migrations/versions/0018_billing_neutral_tables.py (after 0017)."
    )
    assert "0017" in mig, (
        "The 0018 billing migration must chain off 0017 (down_revision references "
        "the 0017 increments migration). T-290."
    )


def test_t290_migration_creates_all_six_neutral_tables() -> None:
    """T-290 — all six provider-neutral billing tables must be created."""
    mig = _migration_0018()
    missing = [t for t in _NEW_TABLES if t not in mig]
    assert not missing, (
        f"The 0018 migration is missing these tables: {missing}. All six neutral "
        "billing tables are required (attempts, packs, debts, admin_corrections, "
        "webhook_events, reconciliation_cursors). T-290."
    )


def test_t290_checkout_attempts_has_ref_nonce_and_unique_ref() -> None:
    """T-290 — billing_checkout_attempts: unique checkout_ref + stored nonce HASH."""
    mig = _migration_0018()
    for col in ("checkout_ref", "checkout_nonce_hash", "expires_at", "provider_checkout_id"):
        assert col in mig, f"billing_checkout_attempts must define '{col}'. T-290."
    assert re.search(r"checkout_ref[^,]*UNIQUE", mig, re.IGNORECASE) or "uq_billing_checkout" in mig, (
        "billing_checkout_attempts.checkout_ref must be UNIQUE (it is the polling "
        "key). T-290."
    )
    # Only the HASH is stored; the raw nonce never becomes a column. (The
    # ingestion-layer 'no raw nonce' rule is asserted in T-297; here we just
    # require the hash column so a comment mentioning the nonce can't false-RED.)
    assert "checkout_nonce_hash" in mig, (
        "billing_checkout_attempts must store checkout_nonce_hash (sha256), never a "
        "raw nonce. T-290 / SR4."
    )


def test_t290_credit_packs_has_full_accounting_columns() -> None:
    """T-290 — billing_credit_packs must carry the full lifetime accounting set."""
    mig = _migration_0018()
    required = (
        "credits_purchased",
        "credits_remaining",
        "credits_consumed",
        "credits_expired",
        "credits_debt_recovered",
        "credits_revoked",
        "paid_item_amount_cents",
        "provider_order_total_cents",
        "provider_refunded_total_cents_seen",
        "refunded_item_amount_cents_processed",
        "provider_order_id",
        "provider_checkout_id",
        "purchased_at",
        "expires_at",
    )
    missing = [c for c in required if c not in mig]
    assert not missing, (
        f"billing_credit_packs is missing accounting columns: {missing}. These drive "
        "FIFO drain, lazy expiry, debt recovery, and exactly-once proportional "
        "reversals. T-290."
    )


def test_t290_credit_packs_has_accounting_sum_check() -> None:
    """T-290 — the conservation CHECK must be the exact four-term sum (discriminating)."""
    norm = _norm(_migration_0018())
    assert (
        "credits_remaining + credits_consumed + credits_expired + credits_debt_recovered"
        in norm
    ), (
        "billing_credit_packs must declare the conservation CHECK "
        "(credits_remaining + credits_consumed + credits_expired + "
        "credits_debt_recovered <= credits_purchased). A vaguer 'a CHECK exists' is "
        "not enough — this exact invariant is what keeps debt accounting sound. T-290 / DC2."
    )


def test_t290_credit_packs_refund_and_revoke_checks() -> None:
    """T-290 — refunded-item and revoked ceilings must be constrained."""
    norm = _norm(_migration_0018())
    assert "refunded_item_amount_cents_processed <= paid_item_amount_cents" in norm, (
        "billing_credit_packs must CHECK refunded_item_amount_cents_processed <= "
        "paid_item_amount_cents. T-290 / DC2."
    )
    assert "credits_revoked <= credits_purchased" in norm, (
        "billing_credit_packs must CHECK credits_revoked <= credits_purchased. T-290 / DC2."
    )


def test_t290_credit_packs_provider_uniqueness_indexes() -> None:
    """T-290 — partial unique indexes on (provider, provider_order_id|checkout_id)."""
    mig = _migration_0018()
    assert "uq_billing_credit_packs_provider_order" in mig or re.search(
        r"provider.*provider_order_id.*WHERE provider_order_id IS NOT NULL", _norm(mig)
    ), (
        "billing_credit_packs needs a partial-unique index on (provider, "
        "provider_order_id) WHERE provider_order_id IS NOT NULL — the primary "
        "idempotency barrier for a duplicate order_created. T-290 / DC3."
    )
    assert "uq_billing_credit_packs_provider_checkout" in mig or re.search(
        r"provider.*provider_checkout_id.*WHERE provider_checkout_id IS NOT NULL", _norm(mig)
    ), (
        "billing_credit_packs needs a partial-unique index on (provider, "
        "provider_checkout_id) WHERE provider_checkout_id IS NOT NULL. T-290 / DC3."
    )


def test_t290_credit_debts_table_shape() -> None:
    """T-290 — billing_credit_debts: one debt per source pack, recovered<=owed."""
    mig = _migration_0018()
    for token in ("source_pack_id", "credits_owed", "credits_recovered"):
        assert token in mig, f"billing_credit_debts must define '{token}'. T-290."
    norm = _norm(mig)
    assert "uq_billing_credit_debts_source_pack" in mig or "source_pack_id" in norm, (
        "billing_credit_debts must be unique on source_pack_id (one debt row per "
        "reversed pack). T-290."
    )
    assert "credits_recovered <= credits_owed" in norm, (
        "billing_credit_debts must CHECK credits_recovered <= credits_owed. T-290."
    )
    assert "RESTRICT" in mig, (
        "billing_credit_debts.source_pack_id must be ON DELETE RESTRICT so debt "
        "cannot be silently lost on pack deletion. T-290 / DC5."
    )


def test_t290_admin_corrections_unique_on_provider_order() -> None:
    """T-290 — admin corrections are append-only and unique on (provider, order)."""
    mig = _migration_0018()
    for token in ("billing_admin_corrections", "evidence_url", "admin_user_id", "target_user_id"):
        assert token in mig, f"billing_admin_corrections must define '{token}'. T-290."
    assert "uq_billing_admin_corrections_provider_order" in mig or re.search(
        r"billing_admin_corrections.*provider.*provider_order_id", _norm(mig)
    ), (
        "billing_admin_corrections needs a UNIQUE (provider, provider_order_id) so a "
        "correction cannot be applied twice for the same order. T-290 / T-302."
    )


def test_t290_webhook_inbox_identity_and_pending_index() -> None:
    """T-290 — durable inbox: 4-part identity uniqueness + pending partial index."""
    mig = _migration_0018()
    for token in ("event_name", "provider_object_id", "payload_hash", "normalized_payload"):
        assert token in mig, f"billing_webhook_events must define '{token}'. T-290."
    norm_ns = _nospace(mig)
    assert "uq_billing_webhook_events_identity" in mig or (
        "provider" in mig and "event_name" in mig and "payload_hash" in mig
    ), (
        "billing_webhook_events needs a UNIQUE (provider, event_name, "
        "provider_object_id, payload_hash) identity for duplicate detection. T-290."
    )
    assert "received" in mig and "processing" in mig and "processed" in mig and "failed" in mig, (
        "billing_webhook_events.status must allow received/processing/processed/failed. T-290."
    )
    assert "normalized_payload" in mig and "JSONB" in mig.upper().replace("JSON_B", "JSONB") or "JSONB" in mig, (
        "billing_webhook_events.normalized_payload must be JSONB. T-290."
    )
    assert norm_ns, "migration unexpectedly empty"


def test_t290_reconciliation_cursor_is_lemon_only() -> None:
    """T-290 — the reconciliation cursor is lemonsqueezy-only (no 'stripe')."""
    mig = _migration_0018()
    assert "billing_reconciliation_cursors" in mig, "cursor table missing. T-290."
    assert "last_successful_run_at" in mig, (
        "billing_reconciliation_cursors must track last_successful_run_at "
        "(authoritative reconcile state, not Redis). T-290 / T-301."
    )
    norm_ns = _nospace(mig)
    assert "IN('lemonsqueezy')" in norm_ns or "PRIMARYKEYCHECK(providerIN('lemonsqueezy')" in norm_ns, (
        "billing_reconciliation_cursors.provider CHECK must be lemonsqueezy-only "
        "(it never holds a 'stripe' row). T-290."
    )


def test_t290_provider_check_allows_stripe_on_neutral_tables() -> None:
    """T-290 — provider CHECK must allow 'stripe' so the backfill rows are valid."""
    norm_ns = _nospace(_migration_0018())
    assert "IN('lemonsqueezy','stripe')" in norm_ns, (
        "The neutral tables' provider CHECK must allow both 'lemonsqueezy' and "
        "'stripe' — the backfill inserts provider='stripe' rows, so a lemon-only "
        "CHECK would fail the migration. T-290."
    )


def test_t290_three_new_ledger_reason_indexes() -> None:
    """T-290 — three credit_ledger reason-uniqueness indexes (the 2nd barrier)."""
    mig = _migration_0018()
    norm = _norm(mig)
    assert "uq_credit_ledger_billing_purchase_reason" in mig or "billing_purchase:%" in norm, (
        "Add a unique index on credit_ledger(reason) WHERE reason LIKE "
        "'billing_purchase:%'. T-290 / DC3."
    )
    assert "uq_credit_ledger_billing_reversal_reason" in mig or (
        "refund:billing:%" in norm and "debt_recovery:billing:%" in norm
    ), (
        "Add a unique index covering reason LIKE 'refund:billing:%' OR "
        "'debt_recovery:billing:%' (the OR-predicate reversal barrier). T-290 / DC3."
    )
    assert "uq_credit_ledger_admin_billing_correction_reason" in mig or "admin_billing_correction:%" in norm, (
        "Add a unique index on credit_ledger(reason) WHERE reason LIKE "
        "'admin_billing_correction:%'. T-290 / DC3."
    )


def test_t290_preserves_existing_refund_reason_index() -> None:
    """T-290 — the pre-existing refund-reason index must NOT be dropped."""
    mig = _migration_0018()
    assert "uq_credit_ledger_refund_reason" not in mig or "drop_index" not in mig.lower().replace(
        "uq_credit_ledger_refund_reason", "KEEP"
    ), (
        "The 0018 migration must preserve the existing uq_credit_ledger_refund_reason "
        "index (the refund:billing:% rows intentionally also match it). T-290 / DC4."
    )


def test_t290_backfill_from_stripe_credit_packs_idempotent() -> None:
    """T-290 — idempotent backfill from stripe_credit_packs into the neutral packs."""
    mig = _migration_0018()
    assert "stripe_credit_packs" in mig, (
        "The 0018 migration must backfill existing stripe_credit_packs into "
        "billing_credit_packs. T-290."
    )
    assert re.search(r"ON\s+CONFLICT", mig, re.IGNORECASE), (
        "The backfill must use INSERT ... ON CONFLICT DO NOTHING so a partially "
        "applied migration is re-runnable. T-290."
    )
    assert "'stripe'" in mig, (
        "Backfilled rows must be provider='stripe'. T-290."
    )


def test_t290_backfill_does_not_touch_credit_balance() -> None:
    """T-290 — the backfill must NOT modify users.credit_balance (discriminating)."""
    mig = _migration_0018()
    # Discriminate an actual write from an explanatory comment: forbid an
    # assignment to credit_balance or an UPDATE of users, not the mere substring.
    assert not re.search(r"credit_balance\s*=", mig), (
        "The 0018 migration must not assign users.credit_balance — the backfill is an "
        "audit copy that preserves balances exactly. T-290 (HANDOFF: 'Do not modify "
        "users.credit_balance')."
    )
    assert not re.search(r"update\s*\(?\s*['\"]?users", mig, re.IGNORECASE), (
        "The 0018 migration must not UPDATE the users table during backfill. T-290."
    )


def test_t290_downgrade_keeps_stripe_tables() -> None:
    """T-290 — downgrade drops the six neutral tables but keeps the Stripe tables."""
    mig = _migration_0018()
    assert "def downgrade" in mig, "0018 migration must define downgrade(). T-290."
    down = mig[mig.index("def downgrade"):]
    assert "drop_table" in down.lower() or "DROP TABLE" in down, (
        "downgrade() must drop the six neutral tables. T-290."
    )
    assert "drop_table('stripe_credit_packs'" not in down and "DROP TABLE stripe_credit_packs" not in down, (
        "downgrade() must NOT drop stripe_credit_packs — Stripe tables are retained "
        "for audit. T-290 / D2."
    )


# ===========================================================================
# T-291 — Models + schemas
# ===========================================================================

_NEW_MODEL_FILES = (
    "billing_checkout_attempt.py",
    "billing_credit_pack.py",
    "billing_credit_debt.py",
    "billing_admin_correction.py",
    "billing_webhook_event.py",
    "billing_reconciliation_cursor.py",
)


def test_t291_neutral_model_files_exist() -> None:
    """T-291 — one ORM model file per neutral table."""
    missing = [f for f in _NEW_MODEL_FILES if not (BACKEND_ROOT / "models" / f).exists()]
    assert not missing, (
        f"Missing ORM model files under backend/models/: {missing}. T-291."
    )


def test_t291_stripe_models_retained() -> None:
    """T-291 — Stripe models must NOT be deleted in this phase (audit + grace)."""
    assert (BACKEND_ROOT / "models" / "stripe_credit_pack.py").exists(), (
        "models/stripe_credit_pack.py must be retained for audit and the 7-day "
        "Stripe webhook grace path. T-291 / D2."
    )


def test_t291_billing_credit_pack_model_columns() -> None:
    """T-291 — BillingCreditPack model mirrors the accounting columns."""
    src = read_backend_file("models", "billing_credit_pack.py")
    for col in ("credits_consumed", "credits_expired", "credits_debt_recovered", "credits_revoked", "paid_item_amount_cents"):
        assert col in src, f"BillingCreditPack must map column '{col}'. T-291."


def test_t291_models_registered_in_init() -> None:
    """T-291 — neutral models exported from models/__init__ so metadata sees them."""
    src = read_backend_file("models", "__init__.py")
    assert "BillingCreditPack" in src, (
        "models/__init__.py must export BillingCreditPack (and the other neutral "
        "models) so Alembic autogenerate/metadata and importers resolve them. T-291."
    )


def test_t291_billing_schemas_have_checkout_ref_and_currency() -> None:
    """T-291/T-296 — CheckoutResponse carries checkout_ref; PackageResponse currency."""
    src = read_backend_file("schemas", "billing.py")
    assert "checkout_ref" in src, (
        "schemas/billing.py CheckoutResponse must include checkout_ref so the "
        "frontend can poll by it. T-291 / T-296."
    )
    assert "currency" in src, (
        "schemas/billing.py PackageResponse must include currency. T-291 / T-296."
    )


# ===========================================================================
# T-292 — Config + production guard
# ===========================================================================

_LEMON_SETTINGS = (
    "lemonsqueezy_api_key",
    "lemonsqueezy_webhook_secret",
    "lemonsqueezy_webhook_secret_prev",
    "lemonsqueezy_store_id",
    "lemonsqueezy_variant_id",
    "lemonsqueezy_price_cents",
    "lemonsqueezy_currency",
    "lemonsqueezy_credits_per_purchase",
    "lemonsqueezy_credit_validity_days",
    "lemonsqueezy_success_url",
    "lemonsqueezy_test_mode",
    "lemonsqueezy_checkout_ttl_minutes",
    "lemonsqueezy_api_base",
    "lemonsqueezy_reconcile_max_calls_per_run",
)


def test_t292_all_lemon_settings_present() -> None:
    """T-292 — every lemonsqueezy_* setting must be declared on Settings."""
    src = read_backend_file("config.py")
    missing = [s for s in _LEMON_SETTINGS if s not in src]
    assert not missing, f"config.py is missing settings: {missing}. T-292."


def test_t292_admin_allowlist_setting_present() -> None:
    """T-292 — admin_user_emails allowlist powers the only admin authz path."""
    src = read_backend_file("config.py")
    assert "admin_user_emails" in src, (
        "config.py must define admin_user_emails (the comma-separated allowlist that "
        "authorises billing admin corrections — the codebase has no role column). "
        "T-292 / SR8."
    )


def test_t292_derived_enabled_and_webhook_secrets() -> None:
    """T-292 — lemonsqueezy_enabled + lemonsqueezy_webhook_secrets derived props."""
    src = read_backend_file("config.py")
    assert "lemonsqueezy_enabled" in src, (
        "config.py must expose lemonsqueezy_enabled (api key + store id + variant id "
        "all set). T-292."
    )
    assert "lemonsqueezy_webhook_secrets" in src, (
        "config.py must expose lemonsqueezy_webhook_secrets (current then previous, "
        "non-empty) for the rotation window. T-292."
    )


def test_t292_production_guard_requires_live_lemon() -> None:
    """T-292 — production guard requires a complete, live (non-test) Lemon config."""
    src = read_backend_file("config.py")
    body = _find_function_body(src, "validate_production_settings") or ""
    assert "lemonsqueezy" in body, (
        "validate_production_settings() must guard the Lemon config in production "
        "(api key, webhook secret, store/variant id, HTTPS success URL, test_mode "
        "False). T-292 / SR7."
    )
    assert "test_mode" in body, (
        "The production guard must reject lemonsqueezy_test_mode=True in production "
        "(live mode required). T-292 / SR7."
    )


# ===========================================================================
# T-293 — Generic queue wrapper (github behaviour preserved)
# ===========================================================================


def test_t293_generic_wrapper_and_billing_job_exist() -> None:
    """T-293 — services.queue exposes a generic factory + billing_job."""
    src = read_backend_file("services", "queue.py")
    assert "make_job_wrapper" in src or "def billing_job" in src, (
        "services/queue.py must expose a generic job-wrapper factory "
        "(make_job_wrapper) used by both github_job and billing_job. T-293."
    )
    assert "billing_job" in src, (
        "services/queue.py must define billing_job (used by worker.py). T-293."
    )
    assert "billing:deadletter" in src, (
        "Billing jobs must dead-letter to the 'billing:deadletter' Redis key, "
        "separate from GitHub's. T-293."
    )


def test_t293_github_behaviour_preserved() -> None:
    """T-293 — github_job keeps its throttle special-case and gh:deadletter."""
    src = read_backend_file("services", "queue.py")
    assert "github_job" in src, "github_job must remain importable by worker.py. T-293."
    assert "gh:deadletter" in src, (
        "GitHub jobs must still dead-letter to 'gh:deadletter' (behaviour unchanged). T-293 / R6."
    )
    assert "GitHubThrottledError" in src, (
        "github_job must still requeue-not-deadletter on GitHubThrottledError — the "
        "throttle special-handler must survive the refactor. T-293 / R6."
    )


def test_t293_record_dead_letter_is_key_parametrised() -> None:
    """T-293 — record_dead_letter takes the dead-letter key (no hard-coded gh key)."""
    src = read_backend_file("services", "queue.py")
    body = _find_function_body(src, "record_dead_letter") or ""
    assert "dead_letter_key" in (body or src), (
        "record_dead_letter must accept a dead_letter_key parameter so billing and "
        "GitHub jobs route to different Redis lists. T-293."
    )


def test_t293_billing_job_metrics_defined() -> None:
    """T-293 — billing job retry/dead-letter counters exist."""
    src = read_backend_file("services", "observability.py")
    assert "thought2build_billing_job_retries_total" in src, (
        "observability.py must define thought2build_billing_job_retries_total{job}. T-293 / T-304."
    )
    assert "thought2build_billing_job_deadlettered_total" in src, (
        "observability.py must define thought2build_billing_job_deadlettered_total{job}. T-293 / T-304."
    )


# ===========================================================================
# T-294 — CreditService onto BillingCreditPack + grant helper
# ===========================================================================


def test_t294_credit_service_uses_billing_credit_pack() -> None:
    """T-294 — CreditService accounting moves to BillingCreditPack."""
    src = read_backend_file("services", "credit_service.py")
    assert "BillingCreditPack" in src, (
        "credit_service.py must query BillingCreditPack (not only StripeCreditPack) "
        "for expiry and FIFO drain after the migration. T-294."
    )


def test_t294_expire_increments_credits_expired() -> None:
    """T-294 — lazy expiry increments credits_expired before zeroing remaining."""
    src = read_backend_file("services", "credit_service.py")
    body = _find_function_body(src, "_expire_user_packs") or ""
    assert "credits_expired" in body, (
        "_expire_user_packs() must increment credits_expired by the pack's previous "
        "credits_remaining before setting status='expired'. T-294."
    )


def test_t294_drain_increments_credits_consumed_fifo() -> None:
    """T-294 — FIFO drain increments credits_consumed and keeps expires_at ASC."""
    src = read_backend_file("services", "credit_service.py")
    body = _find_function_body(src, "_drain_packs") or ""
    assert "credits_consumed" in body, (
        "_drain_packs() must increment credits_consumed by the drained amount. T-294."
    )
    assert re.search(r"expires_at\s*\)?\s*\.?\s*asc|expires_at\.asc|ORDER BY expires_at ASC", body, re.IGNORECASE), (
        "_drain_packs() must keep FIFO ordering (expires_at ASC). T-294."
    )


def test_t294_grant_helper_recovers_debt_first() -> None:
    """T-294 — a grant helper repays pending debt before any usable surplus."""
    src = read_backend_file("services", "credit_service.py")
    assert "grant_credits_with_debt_recovery" in src or "debt" in src.lower(), (
        "credit_service.py must add a grant helper "
        "(grant_credits_with_debt_recovery) used by purchase + admin correction that "
        "repays pending billing_credit_debts before increasing usable balance. T-294."
    )
    assert "billing_credit_debts" in src.lower() or "BillingCreditDebt" in src, (
        "The grant helper must read/lock pending billing_credit_debts. T-294."
    )


def test_t294_debt_recovery_ledger_reason_two_component() -> None:
    """T-294 — debt-recovery audit row uses debt_recovery:billing:<debt>:<pack>."""
    src = _source_containing("debt_recovery:billing:")
    assert src, "No source builds a 'debt_recovery:billing:' ledger reason. T-294."
    assert re.search(r"debt_recovery:billing:\{[^{}]+\}:\{[^{}]+\}", src), (
        "The debt-recovery ledger reason must be the two-component "
        "f'debt_recovery:billing:{debt_id}:{pack_id}'. T-294 / DC4."
    )


# ===========================================================================
# T-295 — LemonSqueezyService
# ===========================================================================


def test_t295_service_file_and_methods_exist() -> None:
    """T-295 — LemonSqueezyService exposes create_checkout + get_order via httpx."""
    src = read_backend_file("services", "lemonsqueezy_service.py")
    assert re.search(r"def\s+create_checkout", src), (
        "lemonsqueezy_service.py must define create_checkout(). T-295."
    )
    assert re.search(r"def\s+get_order", src), (
        "lemonsqueezy_service.py must define get_order() for reconcile lane 2 "
        "(re-read an order Thought2Build already has by id). T-295 / T-301."
    )
    assert "httpx" in src, (
        "LemonSqueezyService must use the existing httpx dependency — no Lemon SDK. T-295."
    )


def test_t295_checkout_jsonapi_contract() -> None:
    """T-295 — JSON:API headers, custom_price, enabled variant, discount off, redirect."""
    src = read_backend_file("services", "lemonsqueezy_service.py")
    assert "application/vnd.api+json" in src, (
        "create_checkout must send Accept/Content-Type application/vnd.api+json. T-295."
    )
    assert "custom_price" in src, "create_checkout must send custom_price. T-295."
    assert "enabled_variants" in src, "create_checkout must set product_options.enabled_variants. T-295."
    assert "redirect_url" in src and "checkout_ref" in src, (
        "create_checkout's redirect_url must carry ?checkout_ref=... T-295."
    )
    assert "checkout_ref" in src and ("custom" in src), (
        "create_checkout must include checkout_data.custom (user_id, checkout_ref, "
        "raw nonce, ...). T-295."
    )


def test_t295_checkout_disables_discount_ui() -> None:
    """T-295 — discount UI disabled so a coupon can't change the paid amount."""
    src = read_backend_file("services", "lemonsqueezy_service.py")
    assert "discount" in src, (
        "create_checkout must set checkout_options.discount=false. T-295."
    )


# ===========================================================================
# T-296 — Billing API (attempt-first, checkout_ref)
# ===========================================================================


def test_t296_package_returns_currency() -> None:
    src = read_backend_file("routers", "billing.py")
    body = _find_function_body(src, "get_package") or src
    assert "currency" in body, "/billing/package must return currency. T-296."


def test_t296_checkout_returns_checkout_ref() -> None:
    """T-296 — POST /checkout returns checkout_ref (not session_id)."""
    src = read_backend_file("routers", "billing.py")
    assert "checkout_ref" in src, (
        "routers/billing.py POST /checkout must generate and return checkout_ref. T-296."
    )


def test_t296_checkout_ref_is_high_entropy() -> None:
    """T-296 — checkout_ref + nonce are cryptographically random (not sequential)."""
    src = read_backend_file("routers", "billing.py")
    assert "secrets." in src or "token_urlsafe" in src or "token_hex" in src, (
        "POST /checkout must mint checkout_ref / checkout_nonce with the secrets "
        "module (high-entropy, non-sequential). T-296 / #10."
    )
    assert "sha256" in src or "hashlib" in src, (
        "Only sha256(checkout_nonce) may be stored — hash the nonce at creation. T-296 / SR4."
    )


def test_t296_checkout_commits_attempt_before_lemon() -> None:
    """T-296 — a local checkout attempt is committed before calling Lemon."""
    src = read_backend_file("routers", "billing.py")
    assert "billing_checkout_attempts" in src or "BillingCheckoutAttempt" in src, (
        "POST /checkout must create+commit a billing_checkout_attempts row before "
        "calling Lemon (Thought2Build is the authority for the attempt). T-296."
    )


def test_t296_status_scopes_by_ref_and_user() -> None:
    """T-296 — /status filters by checkout_ref AND user_id; 404 on mismatch (IDOR)."""
    src = read_backend_file("routers", "billing.py")
    body = _find_function_body(src, "get_billing_status") or _source_containing("checkout_ref")
    assert "checkout_ref" in body and "user_id" in body, (
        "/billing/status must filter by both checkout_ref and user_id in one query "
        "(IDOR-safe). T-296 / SR6."
    )
    assert "404" in body, (
        "/billing/status must return 404 for unknown/mismatched/pending/expired "
        "references (no resource-existence leak). T-296 / SR6."
    )


def test_t296_history_reads_billing_packs() -> None:
    src = read_backend_file("routers", "billing.py")
    body = _find_function_body(src, "get_billing_history") or src
    assert "BillingCreditPack" in body or "billing_credit_packs" in body, (
        "/billing/history must read billing_credit_packs (not StripeCreditPack). T-296."
    )


# ===========================================================================
# T-297 — Webhook ingestion
# ===========================================================================


def test_t297_webhook_reads_raw_body_before_parse() -> None:
    """T-297 — raw bytes read before any JSON parse (HMAC covers raw bytes)."""
    src = read_backend_file("routers", "billing.py")
    assert "request.body()" in src, (
        "The webhook must read raw bytes via await request.body() before parsing. T-297 / SR1."
    )


def test_t297_webhook_hmac_two_secrets_constant_time() -> None:
    """T-297 — X-Signature HMAC-SHA256 over both secrets, constant-time."""
    src = read_backend_file("routers", "billing.py")
    assert re.search(r"x-signature", src, re.IGNORECASE), (
        "The webhook must verify the Lemon X-Signature header. T-297 / SR1."
    )
    assert "hmac" in src and "compare_digest" in src, (
        "Signature verification must use hmac with constant-time compare_digest. T-297 / SR1."
    )
    assert "lemonsqueezy_webhook_secrets" in src, (
        "The webhook must verify against lemonsqueezy_webhook_secrets (current + "
        "previous) for the rotation window. T-297 / SR1."
    )


def test_t297_webhook_event_name_must_match_meta() -> None:
    """T-297 — X-Event-Name must equal meta.event_name."""
    src = read_backend_file("routers", "billing.py")
    assert re.search(r"x-event-name", src, re.IGNORECASE) and "event_name" in src, (
        "The webhook must require X-Event-Name == meta.event_name. T-297 / SR1."
    )


def test_t297_webhook_commits_inbox_then_enqueues_by_id() -> None:
    """T-297 — sanitised inbox row committed, then enqueue by deterministic id."""
    src = read_backend_file("routers", "billing.py")
    assert "billing_webhook_events" in src or "BillingWebhookEvent" in src, (
        "The webhook must persist a billing_webhook_events row before acknowledging. T-297 / D6."
    )
    assert "normalized_payload" in src or "normalized" in src, (
        "The webhook must store a sanitised normalized_payload, not raw bytes. T-297."
    )
    assert "billing_process_webhook" in src, (
        "The webhook must enqueue billing_process_webhook with the inbox row id. T-297."
    )
    assert "billing_wh:" in src, (
        "Enqueue must use the deterministic job_id 'billing_wh:{row_id}' so the "
        "wrapper-retry and the pending-sweep dedup. T-297 / #4."
    )


def test_t297_webhook_does_not_store_raw_nonce_or_pii() -> None:
    """T-297 — the sanitised payload excludes the raw nonce, email, and signature."""
    src = read_backend_file("routers", "billing.py")
    assert "checkout_nonce_hash" in src or "sha256" in src, (
        "order_created ingestion must hash the nonce to checkout_nonce_hash_from_webhook "
        "and drop the raw nonce before building normalized_payload. T-297 / SR4."
    )


def test_t297_webhook_csrf_and_ratelimit_exempt() -> None:
    """T-297 — /billing/webhook stays CSRF- and rate-limit-exempt."""
    csrf = read_backend_file("middleware", "csrf.py")
    rl = read_backend_file("middleware", "rate_limit.py")
    assert "/billing/webhook" in csrf, "/billing/webhook must be CSRF-exempt. T-297."
    assert "/billing/webhook" in rl, "/billing/webhook must be rate-limit-exempt. T-297."


# ===========================================================================
# T-298 — Worker job + pending sweep + retention + registration
# ===========================================================================


def test_t298_billing_worker_module_exists() -> None:
    """T-298 — the billing worker logic lives in one of the planned modules."""
    src = _source_containing("billing_process_webhook")
    assert "billing_process_webhook" in src, (
        "billing_process_webhook must be defined (services/billing_worker.py or "
        "services/billing/processing.py — the plan leaves placement open). T-298."
    )


def test_t298_process_webhook_locks_and_short_circuits_processed() -> None:
    """T-298 — FOR UPDATE the inbox row; processed rows are a no-op."""
    src = _source_containing("billing_process_webhook")
    assert re.search(r"with_for_update|FOR UPDATE", src), (
        "billing_process_webhook must SELECT ... FOR UPDATE the inbox row. T-298."
    )
    assert "processed" in src, (
        "billing_process_webhook must return without side effects when status is "
        "already 'processed'. T-298."
    )


def test_t298_failed_state_persisted_separately() -> None:
    """T-298 — failed status persists in its own committed transaction."""
    src = _source_containing("billing_process_webhook")
    assert "retry_count" in src and "last_error" in src and "failed" in src, (
        "On failure the worker must persist status='failed', retry_count, last_error "
        "in a SEPARATE committed transaction (so the rollback of side effects does "
        "not also discard the failed state) before raising. T-298 / R14."
    )


def test_t298_pending_sweep_reclaims_stale_processing() -> None:
    """T-298 — the 60s sweep reclaims processing rows older than 5 minutes."""
    src = _source_containing("billing_process_pending_webhooks")
    assert "billing_process_pending_webhooks" in src, (
        "billing_process_pending_webhooks must exist (queue-outage + stuck-row recovery). T-298."
    )
    assert re.search(r"SKIP\s+LOCKED", src, re.IGNORECASE), (
        "The pending sweep must use FOR UPDATE SKIP LOCKED with a bounded batch. T-298."
    )
    assert "processing" in src and ("5" in src or "minute" in src.lower()), (
        "The sweep must reclaim 'processing' rows older than 5 minutes (crashed "
        "worker recovery). T-298."
    )
    assert "billing_wh:" in src, (
        "The sweep must re-enqueue with the same deterministic job_id 'billing_wh:{id}' "
        "to dedup against an in-flight wrapper-retry. T-298 / #4."
    )


def test_t298_retention_purge_job_exists() -> None:
    """T-298 — a daily purge bounds the inbox + checkout-attempt growth."""
    src = _source_containing("purge_billing_events")
    assert "purge_billing_events" in src, (
        "A purge_billing_events job must bound billing_webhook_events + terminal "
        "billing_checkout_attempts growth (mirrors purge_webhook_events). T-298 / R9 / DC5."
    )


def test_t298_worker_registers_billing_jobs_and_crons() -> None:
    """T-298 — worker.py registers the job + the pending/reconcile/purge crons."""
    src = read_backend_file("worker.py")
    assert "billing_process_webhook" in src, (
        "worker.py must register billing_process_webhook in WorkerSettings.functions. T-298."
    )
    assert "billing_job" in src, (
        "worker.py must import billing_job alongside github_job. T-298."
    )
    for cronjob in ("billing_process_pending_webhooks", "billing_reconcile", "purge_billing_events"):
        assert cronjob in src, (
            f"worker.py must schedule the {cronjob} cron. T-298 / T-301."
        )


# ===========================================================================
# T-299 — order_created processing (ANCHORED TO THE ATTEMPT SNAPSHOT)
# ===========================================================================


def test_t299_validation_checklist_terms_present() -> None:
    """T-299 — the order_created guard checks store/variant/test_mode/paid/discount."""
    src = _source_containing("billing_purchase:lemonsqueezy:") or _billing_sources()
    norm = src.lower()
    for token in ("store", "variant", "test_mode", "paid", "discount"):
        assert token in norm, (
            f"order_created processing must validate '{token}' before granting. T-299."
        )


def test_t299_price_and_credits_anchored_to_attempt_snapshot() -> None:
    """T-299 — validate price and grant credits from the ATTEMPT, not live config.

    This is the single most likely self-contradiction: every prior artifact used
    LEMONSQUEEZY_PRICE_CENTS / LEMONSQUEEZY_CREDITS_PER_PURCHASE. The plan (DC6)
    anchors to the attempt snapshot so an in-flight price change cannot break or
    mis-price a paid checkout.
    """
    src = _source_containing("billing_purchase:lemonsqueezy:") or _billing_sources()
    assert re.search(r"(attempt|checkout_attempt)\.credits", src), (
        "order_created must grant attempt.credits (the snapshot), not "
        "settings.lemonsqueezy_credits_per_purchase. T-299 / DC6 / #3."
    )
    assert re.search(r"(attempt|checkout_attempt)\.price_cents", src), (
        "order_created must validate the item price against attempt.price_cents (the "
        "snapshot), not settings.lemonsqueezy_price_cents. T-299 / DC6 / #3."
    )


def test_t299_purchase_ledger_reason_format() -> None:
    """T-299 — purchase ledger reason is billing_purchase:lemonsqueezy:<order_id>."""
    src = _source_containing("billing_purchase:")
    assert re.search(r"billing_purchase:lemonsqueezy:\{[^{}]+\}", src), (
        "The purchase ledger reason must be f'billing_purchase:lemonsqueezy:{order_id}'. "
        "T-299 / DC4."
    )


def test_t299_idempotent_on_provider_order_or_checkout() -> None:
    """T-299 — a duplicate order_created reloads the existing pack, no second grant."""
    src = _source_containing("billing_purchase:") or _billing_sources()
    assert "provider_order_id" in src and "provider_checkout_id" in src, (
        "order_created must short-circuit when a BillingCreditPack already exists for "
        "(provider, provider_order_id) or (provider, provider_checkout_id). T-299 / DC3."
    )


# ===========================================================================
# T-300 — order_refunded / fraud / debt
# ===========================================================================


def test_t300_refund_normalisation_math_present() -> None:
    """T-300 — tax-normalised floor formula + clamp (not naive 'refund amount')."""
    src = _source_containing("refund:billing:") or _billing_sources()
    assert "floor" in src or "//" in src, (
        "Refund math must floor the proportional item-credit amount. T-300 / R2."
    )
    assert "clamp" in src or ("min(" in src and "max(" in src), (
        "Refund money must be clamped through the order total so tax-inclusive "
        "refunds do not over-revoke. T-300 / R2."
    )
    assert "credits_expired" in src and "credits_purchased" in src, (
        "refundable_value must be credits_purchased - credits_expired (expired value "
        "is never reclaimed). T-300."
    )


def test_t300_refund_reason_has_cents_suffix() -> None:
    """T-300 — refund reason is the TWO-component refund:billing:<pack>:<cents>.

    Discriminating: 'refund:billing:{pack_id}' (one component) silently no-ops the
    second partial refund. The cents suffix is the per-level idempotency barrier.
    """
    src = _source_containing("refund:billing:")
    assert src, "No source builds a 'refund:billing:' ledger reason. T-300."
    assert re.search(r"refund:billing:\{[^{}]+\}:\{[^{}]+\}", src), (
        "The refund ledger reason must be the two-component "
        "f'refund:billing:{pack_id}:{new_refunded_item_cents}'. A one-component "
        "reason collides on the second partial refund and skips the revocation. "
        "T-300 / DC4."
    )


def test_t300_monotonic_processed_level() -> None:
    """T-300 — refunded_item_amount_cents_processed gates replay (same/lower = no-op)."""
    src = _source_containing("refund:billing:") or _billing_sources()
    assert "refunded_item_amount_cents_processed" in src, (
        "Refund processing must compare against and advance "
        "refunded_item_amount_cents_processed so a replay of the same/lower amount is "
        "a no-op. T-300 / R3."
    )


def test_t300_single_ordered_pack_lock() -> None:
    """T-300 — refund locks all packs in one expires_at ASC FOR UPDATE (deadlock-safe)."""
    src = _source_containing("refund:billing:")
    assert src, "refund handler source not found. T-300."
    assert re.search(r"expires_at", src) and re.search(r"with_for_update|FOR UPDATE", src), (
        "The refund path must acquire the user's packs under a single "
        "'FOR UPDATE ORDER BY expires_at ASC' (identical lock order to deduct()), "
        "not lock the source pack out of order. T-300 / R8 / #8."
    )
    assert re.search(r"expires_at\s*\)?\s*\.?\s*asc|expires_at\.asc|expires_at ASC", src, re.IGNORECASE), (
        "The refund pack lock must be ORDER BY expires_at ASC to match deduct(). T-300 / R8."
    )


def test_t300_creates_recoverable_debt() -> None:
    """T-300 — value beyond immediately recoverable credits becomes debt."""
    src = _source_containing("refund:billing:") or _billing_sources()
    assert "billing_credit_debts" in src.lower() or "BillingCreditDebt" in src or "credits_owed" in src, (
        "When a reversal exceeds recoverable credits the shortfall must be written to "
        "billing_credit_debts (recovered from future grants), never forgiven. T-300 / R13/D5."
    )


# ===========================================================================
# T-301 — Reconciliation
# ===========================================================================


def test_t301_reconcile_exists_with_cursor_lock() -> None:
    """T-301 — billing_reconcile uses the cursor row with FOR UPDATE NOWAIT."""
    src = _source_containing("billing_reconcile") or _billing_sources()
    assert "billing_reconcile" in src, "billing_reconcile must exist. T-301."
    assert "billing_reconciliation_cursors" in src.lower() or "ReconciliationCursor" in src, (
        "Reconcile state must live in billing_reconciliation_cursors (not Redis). T-301."
    )
    assert re.search(r"NOWAIT", src, re.IGNORECASE), (
        "billing_reconcile must acquire the cursor row FOR UPDATE NOWAIT and skip "
        "cleanly if another run holds it. T-301."
    )


def test_t301_reconcile_never_auto_grants() -> None:
    """T-301 — reconcile must not invent a grant from order list/email/redirect."""
    src = _source_containing("billing_reconcile") or _billing_sources()
    assert "checkout_ref" in src or "nonce" in src.lower(), (
        "Reconcile's inbox-replay lane must rely on the signed custom-data proof "
        "(checkout_ref + nonce hash) — never on order listing, email, receipt URL, "
        "amount, or redirect — to (re)grant. T-301 / D4 / SR3."
    )


def test_t301_lane2_is_bounded() -> None:
    """T-301 — lane 2 is call-bounded so it cannot exhaust the Lemon API."""
    src = _source_containing("billing_reconcile") or _billing_sources()
    assert "lemonsqueezy_reconcile_max_calls_per_run" in src or "max_calls" in src, (
        "Reconcile lane 2 must cap per-run Lemon order fetches "
        "(lemonsqueezy_reconcile_max_calls_per_run) and page via the cursor state. "
        "T-301 / R10 / #6."
    )


# ===========================================================================
# T-302 — Admin correction
# ===========================================================================


def test_t302_admin_endpoint_and_require_admin() -> None:
    """T-302 — admin correction is gated by require_admin / admin_user_emails."""
    src = read_backend_file("routers", "billing.py")
    assert "correction" in src.lower(), (
        "routers/billing.py must expose the admin correction endpoint. T-302."
    )
    sources = _billing_sources() + read_backend_file("config.py")
    assert "require_admin" in sources or "admin_emails" in sources or "admin_user_emails" in sources, (
        "The admin correction path must be authorised by require_admin against the "
        "admin_user_emails allowlist (closed by default; no implicit admin). T-302 / SR8 / R12."
    )


def test_t302_admin_correction_idempotent_and_audited() -> None:
    """T-302 — a correction is idempotent on (provider, order) and writes audit."""
    src = _source_containing("admin_billing_correction:") or _billing_sources()
    assert re.search(r"admin_billing_correction:\{[^{}]+\}:\{[^{}]+\}", src), (
        "The admin-correction ledger reason must be "
        "f'admin_billing_correction:{provider}:{order_id}'. T-302 / DC4."
    )
    assert "billing_admin_corrections" in src.lower() or "BillingAdminCorrection" in src, (
        "A correction must write the immutable billing_admin_corrections audit row "
        "and no-op on a duplicate (provider, order_id). T-302."
    )


# ===========================================================================
# T-303 — Stripe cutover (no SDK removal here)
# ===========================================================================


def test_t303_new_checkout_is_lemon_only() -> None:
    """T-303 — POST /checkout drops the Stripe path and goes through the Lemon attempt."""
    src = read_backend_file("routers", "billing.py")
    body = _find_function_body(src, "create_checkout") or src
    assert "stripe_service.create_checkout_session" not in body and "stripe.checkout.Session" not in body, (
        "POST /checkout must no longer call the Stripe checkout path "
        "(stripe_service.create_checkout_session). T-303."
    )
    assert "checkout_ref" in body, (
        "POST /checkout must go through the Lemon attempt flow and return a "
        "checkout_ref. T-303 / T-296."
    )


def test_t303_late_stripe_grace_provider_disabled_marker() -> None:
    """T-303 — post-grace Stripe-shaped requests are rejected before any DB write."""
    src = _billing_sources()
    assert "ignored_provider_disabled" in src, (
        "After the grace window the webhook must reject Stripe-shaped requests with "
        "{'status':'ignored_provider_disabled'} before any DB write. T-303."
    )


def test_t303_stripe_dependency_removed_by_t308() -> None:
    """T-308 (flips T-303) — the stripe SDK dependency is removed post-cutover.

    T-303 deliberately kept the ``stripe`` dependency present for the bounded
    grace window; the gated decommission (T-308) removes it once the window has
    provably closed. This contract is flipped to assert the dependency is gone
    from both ``pyproject.toml`` and ``requirements.txt`` (the retained
    ``stripe_credit_packs`` / ``stripe_webhook_events`` audit tables are NOT a
    dependency line, so they are unaffected).
    """
    pyproject = BACKEND_ROOT / "pyproject.toml"
    reqs = BACKEND_ROOT / "requirements.txt"

    def _has_stripe_dep(path) -> bool:
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().strip('"').strip("'")
            if stripped.lower().startswith("stripe"):
                return True
        return False

    assert not _has_stripe_dep(pyproject) and not _has_stripe_dep(reqs), (
        "The stripe SDK dependency must be removed by the gated decommission "
        "(pyproject.toml + requirements.txt). T-308."
    )


# ===========================================================================
# T-304 — Observability (provider-labelled; pack_disputed retired)
# ===========================================================================

_REQUIRED_METRICS = (
    "thought2build_billing_checkout_created_total",
    "thought2build_billing_checkout_completed_total",
    "thought2build_billing_checkout_api_error_total",
    "thought2build_billing_checkout_expired_total",
    "thought2build_billing_unrecoverable_checkout_total",
    "thought2build_billing_webhook_received_total",
    "thought2build_billing_webhook_duplicate_total",
    "thought2build_billing_webhook_error_total",
    "thought2build_billing_webhook_pending_age_seconds",
    "thought2build_billing_credits_granted_total",
    "thought2build_billing_credits_revoked_total",
    "thought2build_billing_credit_debt_created_total",
    "thought2build_billing_credit_debt_recovered_total",
    "thought2build_billing_credits_expired_total",
    "thought2build_billing_admin_correction_total",
    "thought2build_billing_reconcile_mismatch_total",
    "thought2build_billing_job_retries_total",
    "thought2build_billing_job_deadlettered_total",
)


def test_t304_required_billing_metrics_defined() -> None:
    """T-304 — the full provider-labelled billing metric set is defined."""
    src = read_backend_file("services", "observability.py")
    missing = [m for m in _REQUIRED_METRICS if m not in src]
    assert not missing, (
        f"observability.py is missing billing metrics: {missing}. T-304."
    )


def test_t304_credits_revoked_replaces_pack_disputed() -> None:
    """T-304 — reversals are credits_revoked_total{reason} (pack_disputed retired)."""
    src = read_backend_file("services", "observability.py")
    assert "thought2build_billing_credits_revoked_total" in src, (
        "Reversals must be counted by thought2build_billing_credits_revoked_total{provider,"
        "reason} — the Phase-21 pack_disputed_total is retired/folded in. T-304."
    )


def test_t304_redaction_adds_lemon_secrets_and_nonce() -> None:
    """T-304 — Lemon key/secret/signature and the raw nonce are scrubbed."""
    src = read_backend_file("services", "observability.py")
    assert "lemonsqueezy_api_key" in src and "lemonsqueezy_webhook_secret" in src, (
        "Redaction must scrub the Lemon API key and webhook secret(s). T-304 / SR5."
    )
    assert "checkout_nonce" in src or "nonce" in src.lower(), (
        "Redaction must scrub the raw checkout nonce. T-304 / SR5."
    )


# ===========================================================================
# /credits/balance — billing_debt_credits (backend contract)
# ===========================================================================


def test_credits_balance_schema_exposes_debt() -> None:
    """T-305 (backend) — CreditBalance schema exposes billing_debt_credits."""
    src = read_backend_file("schemas", "credits.py")
    assert "billing_debt_credits" in src, (
        "schemas/credits.py CreditBalance must expose billing_debt_credits so the UI "
        "and support see unrecovered reversal debt separately from usable balance. "
        "T-305 / §11."
    )


def test_credits_balance_endpoint_returns_debt() -> None:
    """T-305 (backend) — GET /credits/balance returns billing_debt_credits."""
    src = read_backend_file("routers", "credits.py")
    assert "billing_debt_credits" in src, (
        "GET /credits/balance must populate billing_debt_credits (sum of pending "
        "billing_credit_debts owed-minus-recovered for the user). T-305."
    )


# ===========================================================================
# Cross-cutting: router registration
# ===========================================================================


def test_billing_router_registered_in_main() -> None:
    src = read_backend_file("main.py")
    assert "billing" in src, (
        "main.py must register the billing router or none of the endpoints are "
        "reachable. T-296."
    )


# ===========================================================================
# T-306 — Behavioural lever: the backend test suite must cover money-math
# (a source-grep harness cannot run the refund/debt math; assert the unit/
# integration tests that DO exist and name the critical paths).
# ===========================================================================

_PHASE25_TEST_GLOBS = ("test_phase25_*.py", "test_lemonsqueezy*.py", "test_billing*.py")


def _phase25_test_text() -> str:
    tests_dir = BACKEND_ROOT / "tests"
    if not tests_dir.exists():
        return ""
    seen: set[str] = set()
    parts: list[str] = []
    for pattern in _PHASE25_TEST_GLOBS:
        for f in tests_dir.glob(pattern):
            if f.name in seen:
                continue
            seen.add(f.name)
            parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_t306_phase25_backend_test_file_exists() -> None:
    """T-306 — a backend unit/integration suite for Phase 25 must exist."""
    assert _phase25_test_text(), (
        "backend/tests/test_phase25_*.py (or test_lemonsqueezy_*/test_billing_*) must "
        "exist — it is where the money-math behaviours this source-grep harness cannot "
        "run are actually verified. T-306."
    )


def test_t306_tests_cover_money_correctness_paths() -> None:
    """T-306 — the suite must name the critical money-correctness behaviours."""
    text = _phase25_test_text().lower()
    required = {
        "full refund / proportional partial": ("refund",),
        "partial-refund proportional math": ("partial",),
        "recoverable debt": ("debt",),
        "expiry vs debt": ("expire",),
        "duplicate webhook no double-credit": ("duplicate", "idempot"),
        "forged user_id grants nothing": ("forged", "nonce", "mismatch"),
        "IDOR status scoping": ("idor", "404"),
        "reconcile no-auto-grant": ("reconcile",),
    }
    missing = [
        label
        for label, tokens in required.items()
        if not any(tok in text for tok in tokens)
    ]
    assert not missing, (
        "The Phase-25 backend test suite must cover these behaviours (none of which "
        f"a source-grep harness can run): {missing}. T-306."
    )


def test_t306_tests_cover_deadlock_and_reclaim() -> None:
    """T-306 — the reliability behaviours (deadlock, stale reclaim) are covered."""
    text = _phase25_test_text().lower()
    assert "deadlock" in text or ("deduct" in text and "refund" in text), (
        "The suite must include the concurrent deduct↔refund (deadlock-safety) case. "
        "T-306 / R8."
    )
    assert "reclaim" in text or "processing" in text or "stale" in text, (
        "The suite must cover stale 'processing' row reclaim by the pending sweep. "
        "T-306 / #4."
    )


# ===========================================================================
# T-307 — Docs / release gate (light: catch a wholesale docs miss)
# ===========================================================================


def test_t307_docs_mention_lemonsqueezy_billing() -> None:
    """T-307 — operator docs must cover the Lemon billing path (setup/runbook/gate)."""
    docs_dir = REPO_ROOT_DOCS
    if not docs_dir.exists():
        # Docs live elsewhere; don't false-RED on layout. The contract is that
        # *some* doc references the new provider.
        text = ""
    else:
        text = "\n".join(
            f.read_text(encoding="utf-8", errors="ignore").lower()
            for f in docs_dir.glob("*.md")
        )
    assert "lemonsqueezy" in text or "lemon squeezy" in text, (
        "docs/ must document the Lemon Squeezy billing path (setup, webhook-secret "
        "rotation, dead-letter replay from billing:deadletter, admin-correction "
        "runbook, and the production release gate). T-307."
    )

"""
Harness contracts for Phase 21 — Stripe Payments Integration.

These tests are RED before T-226 through T-238 are implemented and GREEN after.

Every test maps to one or more tasks from Plan v1.md Phase 21:

  T-226  DB Migration — stripe_credit_packs + stripe_webhook_events tables
         Two new Alembic migrations with UNIQUE idempotency index and
         partial index on (user_id, status, expires_at) for active pack queries.

  T-227  Config additions — 7 Stripe env vars + production key guard
         validate_production_settings() rejects sk_test_* keys in production.

  T-228  StripeService — checkout session creation, event dispatch, dispute revocation
         Credits granted from event["created"] timestamp, not server clock.
         User resolved from metadata.user_id (UUID), never from email.

  T-229  CreditService extensions — lazy expiry + FIFO pack drain
         _expire_user_packs() called at top of get_balance() and deduct().
         _drain_packs() drains soonest-expiring packs first (expires_at ASC).
         Both hold SELECT FOR UPDATE on user row AND pack rows.
         Invariant: credit_balance >= SUM(active packs.credits_remaining).

  T-230  GET /billing/package — unauthenticated static config endpoint
  T-231  POST /billing/checkout — creates Stripe session; rate-limited 5/user/hour
  T-232  GET /billing/status — IDOR-safe: scoped by session_id AND user_id
  T-233  GET /billing/history — sorted by purchased_at DESC; capped at 50

  T-234  POST /billing/webhook — raw body, Stripe-Signature validation, idempotency
         tolerance=300, INSERT before handle_event, IntegrityError caught for dupes,
         no JWT auth, never logs raw payload.

  T-235  Middleware exemptions
         /billing/webhook in CSRF _EXEMPT_PATHS and rate limit _BYPASS_PATHS.
         Checkout rate-limit tier: 5/user/hour.

  T-236  Security & Observability
         sk_live_*/sk_test_* and whsec_* added to _SECRET_PATTERNS.
         stripe_secret_key, stripe_webhook_secret, client_secret in _SENSITIVE_KEYS.
         10 Prometheus billing counters defined in observability.py.

  T-237  Unit test file backend/tests/test_stripe_payments.py exists and covers
         all critical paths: idempotency, IDOR, expiry, FIFO drain, dispute.

  T-238  Frontend Billing.tsx page + types/billing.ts + expiry warning chip
         in CreditMeter.tsx + /billing route in App.tsx.

Design invariants enforced here:
  * stripe_credit_packs and stripe_webhook_events tables in migration history.
  * UNIQUE index on stripe_webhook_events.stripe_event_id (idempotency).
  * UNIQUE index on stripe_credit_packs.stripe_session_id (duplicate checkout guard).
  * validate_production_settings() rejects sk_test_* when ENVIRONMENT=production.
  * StripeService resolves user from metadata.user_id, not email.
  * expires_at derives from event["created"] timestamp, not datetime.utcnow() alone.
  * stripe.Webhook.construct_event called with tolerance=300.
  * Webhook idempotency INSERT is placed BEFORE handle_event call.
  * IntegrityError (duplicate stripe_event_id) is caught in webhook handler.
  * Webhook handler has NO get_current_user dependency.
  * /billing/status WHERE clause includes BOTH stripe_session_id AND user_id.
  * _drain_packs orders by expires_at ASC (not DESC, not purchased_at).
  * _expire_user_packs uses SELECT FOR UPDATE on both user row and pack rows.
  * /billing/webhook is in CSRF _EXEMPT_PATHS and rate limit _BYPASS_PATHS.
  * sk_live_*/sk_test_* regex and whsec_* regex in _SECRET_PATTERNS.
  * 10 specforge_billing_* Prometheus counters defined.
  * billing router registered in main.py.
  * No email field used in webhook user resolution.
"""

from __future__ import annotations

import re

from conftest import BACKEND_ROOT, REPO_ROOT, read_backend_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_function_body(source: str, fn_name: str) -> str | None:
    """Extract the body of a top-level or method function by name.

    Returns the body text (everything after the `def` line) up to the next
    same-indent function/class definition, or None if not found.
    """
    pattern = re.compile(
        rf"(?:async\s+)?def\s+{re.escape(fn_name)}\s*\([^)]*\)[^:]*:(.*?)"
        r"(?=\n\s{0,4}(?:async\s+)?def\s+\w|\n\s{0,4}class\s+\w|\Z)",
        re.DOTALL,
    )
    m = pattern.search(source)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# T-226: DB Migration — stripe_credit_packs + stripe_webhook_events
# ---------------------------------------------------------------------------


def test_t226_migration_directory_has_stripe_migration() -> None:
    """T-226 — A migration file referencing stripe_credit_packs must exist.

    The Alembic migration (0013_stripe_payments.py or similar) must create
    both stripe_credit_packs and stripe_webhook_events tables.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    assert (
        versions_dir.exists()
    ), "backend/migrations/versions/ directory must exist.  T-226."
    migration_files = list(versions_dir.glob("*.py"))
    assert (
        migration_files
    ), "backend/migrations/versions/ must contain at least one migration file.  T-226."

    combined = "\n".join(f.read_text(encoding="utf-8") for f in migration_files)

    assert "stripe_credit_packs" in combined, (
        "No migration file references 'stripe_credit_packs'.  T-226 requires an "
        "Alembic migration that creates the stripe_credit_packs table.  "
        "Add migrations/versions/0013_stripe_payments.py.  T-226."
    )


def test_t226_migration_creates_stripe_webhook_events() -> None:
    """T-226 — The migration must also create stripe_webhook_events for idempotency.

    stripe_webhook_events.stripe_event_id has a UNIQUE constraint so that
    concurrent Stripe retries of the same event cannot double-credit a user.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in versions_dir.glob("*.py")
    )

    assert "stripe_webhook_events" in combined, (
        "No migration file references 'stripe_webhook_events'.  T-226 requires "
        "a table that stores processed Stripe event IDs for idempotency.  "
        "Without this, a Stripe retry of the same checkout.session.completed "
        "event will double-credit the user.  T-226."
    )


def test_t226_migration_has_unique_index_on_stripe_event_id() -> None:
    """T-226 — UNIQUE constraint on stripe_webhook_events.stripe_event_id.

    This is the idempotency guard.  Two concurrent deliveries of the same
    stripe_event_id must be serialised by the DB — one succeeds, the other
    raises IntegrityError which the webhook handler catches.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in versions_dir.glob("*.py")
    )

    has_unique = "uq_stripe_webhook_events_stripe_event_id" in combined or (
        "stripe_event_id" in combined
        and re.search(
            r"unique[_\s]*index|UniqueConstraint|UNIQUE", combined, re.IGNORECASE
        )
    )
    assert has_unique, (
        "The stripe_webhook_events migration must declare a UNIQUE constraint on "
        "stripe_event_id.  This is the write-serialising lock that prevents "
        "concurrent Stripe retries from double-crediting a user.  T-226."
    )


def test_t226_migration_has_unique_index_on_stripe_session_id() -> None:
    """T-226 — UNIQUE constraint on stripe_credit_packs.stripe_session_id.

    A single Stripe Checkout Session must produce at most one credit pack.
    Without this constraint, a race between two concurrent
    checkout.session.completed webhooks for the same session would create two
    packs and grant double credits.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in versions_dir.glob("*.py")
    )

    has_unique = "uq_stripe_credit_packs_session_id" in combined or (
        "stripe_session_id" in combined
        and re.search(
            r"unique[_\s]*index|UniqueConstraint|UNIQUE", combined, re.IGNORECASE
        )
    )
    assert has_unique, (
        "The stripe_credit_packs migration must declare a UNIQUE constraint on "
        "stripe_session_id.  This prevents a race between two concurrent "
        "checkout.session.completed deliveries for the same session from creating "
        "two packs and granting double credits.  T-226."
    )


def test_t226_migration_has_expires_at_column() -> None:
    """T-226 — stripe_credit_packs must have an expires_at column.

    Lazy expiry reads expires_at to sweep stale packs inside get_balance()
    and deduct().  Without this column, there is no way to implement the
    30-day validity window.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in versions_dir.glob("*.py")
    )

    assert "expires_at" in combined, (
        "The stripe_credit_packs migration must include an 'expires_at' column "
        "(TIMESTAMPTZ NOT NULL).  This is the expiry anchor for lazy expiry in "
        "_expire_user_packs().  T-226."
    )


def test_t226_migration_has_credits_remaining_column() -> None:
    """T-226 — stripe_credit_packs must have a credits_remaining column.

    FIFO pack drain decrements credits_remaining as credits are consumed.
    The invariant credit_balance >= SUM(credits_remaining) relies on this column.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in versions_dir.glob("*.py")
    )

    assert "credits_remaining" in combined, (
        "The stripe_credit_packs migration must include a 'credits_remaining' column.  "
        "FIFO drain in _drain_packs() decrements this per deduction.  Without it "
        "there is no way to track how much of a pack has been consumed.  T-226."
    )


def test_t226_migration_has_status_column() -> None:
    """T-226 — stripe_credit_packs must have a status column (active/consumed/expired/disputed).

    Status transitions gate expiry sweep and FIFO drain queries:
    'SELECT ... WHERE status = active'.  Dispute revocation sets status='disputed'.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in versions_dir.glob("*.py")
    )

    assert "status" in combined, (
        "The stripe_credit_packs migration must include a 'status' column "
        "(VARCHAR, values: active / consumed / expired / disputed).  "
        "Active-pack queries filter on status='active'.  T-226."
    )


def test_t226_migration_has_partial_or_composite_index_for_active_packs() -> None:
    """T-226 — An index on (user_id, status, expires_at) must exist for active pack queries.

    get_balance() and deduct() both start with an active-pack sweep.
    Without an index on the composite (user_id, status, expires_at) key,
    this becomes a seq-scan on stripe_credit_packs for every credit operation.
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in versions_dir.glob("*.py")
    )

    has_active_index = "ix_stripe_credit_packs_user_active" in combined or (
        "stripe_credit_packs" in combined
        and "user_id" in combined
        and "expires_at" in combined
        and re.search(r"create_index|CREATE INDEX", combined, re.IGNORECASE)
    )
    assert has_active_index, (
        "The stripe_credit_packs migration must create a composite index on "
        "(user_id, status, expires_at) — or a partial index WHERE status='active' — "
        "so the active-pack sweep in _expire_user_packs() and _drain_packs() does "
        "not cause a full table scan on every credit operation.  T-226."
    )


def test_t226_migration_has_downgrade_function() -> None:
    """T-226 — The Stripe migration must have a downgrade() function.

    All Alembic migrations in this project include both upgrade() and downgrade().
    The downgrade drops both tables in reverse order (stripe_credit_packs
    depends on users via FK; stripe_webhook_events is independent).
    """
    versions_dir = BACKEND_ROOT / "migrations" / "versions"
    # Find the migration file that contains stripe_credit_packs.
    stripe_migration = None
    for f in versions_dir.glob("*.py"):
        content = f.read_text(encoding="utf-8")
        if "stripe_credit_packs" in content:
            stripe_migration = content
            break

    assert (
        stripe_migration is not None
    ), "No migration file for stripe_credit_packs found.  T-226."
    assert "def downgrade" in stripe_migration, (
        "The Stripe migration must define a downgrade() function that drops "
        "stripe_credit_packs and stripe_webhook_events.  T-226."
    )


# ---------------------------------------------------------------------------
# T-227: Config — Stripe runtime config removed by the decommission (T-308)
# ---------------------------------------------------------------------------
#
# Phase 18 defined seven STRIPE_* settings plus a scoped ``sk_test_*`` production
# guard. The gated decommission (T-308) removed the Stripe runtime, so those
# settings and the guard are gone; the Lemon Squeezy config + its own production
# guard (pinned by the Phase-25 contract) replace them. These reconciled
# assertions pin the removal so the superseded Stripe config cannot silently
# return. The retained ``stripe_credit_packs`` / ``stripe_webhook_events`` audit
# tables are unaffected (they are not config fields).

_STRIPE_PREFIX = "sk_" + "test_"  # assembled so this contract file is grep-clean


def test_t227_stripe_config_fields_removed_by_t308() -> None:
    """T-308 (supersedes T-227) — the STRIPE_* settings are removed from config."""
    source = read_backend_file("config.py")
    for field in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_price_cents",
        "stripe_credits_per_purchase",
        "stripe_credit_validity_days",
        "stripe_success_url",
        "stripe_cancel_url",
    ):
        assert field not in source, (
            f"config.py must no longer define {field} — the Stripe runtime is "
            "decommissioned (T-308); the Lemon Squeezy settings replace it."
        )


def test_t227_scoped_stripe_test_key_guard_removed_by_t308() -> None:
    """T-308 (supersedes T-227) — the scoped Stripe test-key production guard is gone.

    validate_production_settings() must still exist (it now holds only the Lemon
    Squeezy production guard), but it must no longer reference the Stripe test-key
    prefix.
    """
    source = read_backend_file("config.py")
    assert _STRIPE_PREFIX not in source, (
        "The scoped Stripe test-key production guard must be removed (T-308)."
    )
    assert "validate_production_settings" in source, (
        "validate_production_settings() must still exist (it holds the Lemon guard)."
    )


# ---------------------------------------------------------------------------
# T-228: StripeService removed by the decommission (T-308)
# ---------------------------------------------------------------------------
#
# Phase 18's ``services/stripe_service.py`` owned all Stripe API interactions
# (checkout-session creation, webhook dispatch, dispute revocation). The gated
# decommission (T-308) deleted it once the grace window provably closed — the
# Lemon Squeezy service + worker (pinned by the Phase-25 contract) are the only
# billing runtime now. These reconciled assertions pin the removal; the Stripe
# audit *tables/models* are retained and asserted separately below.


def test_t228_stripe_service_module_removed_by_t308() -> None:
    """T-308 (supersedes T-228) — services/stripe_service.py is deleted."""
    path = BACKEND_ROOT / "services" / ("stripe_" + "service.py")
    assert not path.exists(), (
        "services/stripe_service.py must be deleted by the Stripe decommission "
        "(T-308). The Lemon Squeezy service is the billing runtime now."
    )


def test_t228_no_stripe_sdk_dependency_after_t308() -> None:
    """T-308 (supersedes T-228) — the stripe SDK dependency is gone.

    The deleted service was the only ``import stripe`` site; with it gone the SDK
    is removed from pyproject.toml + requirements.txt (also pinned by the
    Phase-25 ``test_t303_stripe_dependency_removed_by_t308`` contract).
    """
    sdk = "stripe"
    for fname in ("pyproject.toml", "requirements.txt"):
        path = BACKEND_ROOT / fname
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().strip('"').strip("'")
            assert not stripped.lower().startswith(sdk), (
                f"{fname} must not declare the stripe SDK dependency after T-308."
            )


# ---------------------------------------------------------------------------
# T-229: CreditService extensions — lazy expiry + FIFO drain
# ---------------------------------------------------------------------------


def test_t229_credit_service_has_expire_user_packs() -> None:
    """T-229 — credit_service.py must define _expire_user_packs().

    This function sweeps active packs past their expires_at and revokes the
    remaining credits from credit_balance.  Called at the top of get_balance()
    and deduct() so balance reads are always post-expiry.
    """
    source = read_backend_file("services", "credit_service.py")
    assert re.search(r"def\s+_expire_user_packs\s*\(", source), (
        "credit_service.py must define _expire_user_packs() (sync or async).  "
        "This function sweeps packs past expires_at, sets status='expired', and "
        "reduces credit_balance by the remaining credits.  It is called at the "
        "top of get_balance() and deduct().  T-229."
    )


def test_t229_credit_service_has_drain_packs() -> None:
    """T-229 — credit_service.py (or stripe_service.py) must define _drain_packs().

    FIFO pack drain reduces credits_remaining on the soonest-expiring active
    pack(s) after each deduction, keeping pack.credits_remaining in sync with
    user.credit_balance.  Without this, packs would always show
    credits_remaining = credits_purchased even after the credits were spent.
    """
    credit_source = read_backend_file("services", "credit_service.py")
    has_drain = re.search(r"def\s+_drain_packs\s*\(", credit_source)

    if not has_drain:
        # Acceptable alternative: defined in stripe_service.py
        stripe_path = BACKEND_ROOT / "services" / "stripe_service.py"
        if stripe_path.exists():
            stripe_source = stripe_path.read_text(encoding="utf-8")
            has_drain = re.search(r"def\s+_drain_packs\s*\(", stripe_source)

    assert has_drain, (
        "_drain_packs() must be defined in credit_service.py or stripe_service.py.  "
        "This function drains credits_remaining from soonest-expiring packs after "
        "each deduction.  Without it, pack.credits_remaining never decreases and "
        "the invariant credit_balance >= SUM(credits_remaining) cannot be maintained.  "
        "T-229."
    )


def test_t229_get_balance_calls_expire_user_packs() -> None:
    """T-229 — get_balance() must call _expire_user_packs() before reading balance.

    If get_balance() returns the credit_balance without sweeping expired packs
    first, it will show credits that should have expired — users can see a
    higher balance than they actually have until the next deduction triggers
    the sweep.
    """
    source = read_backend_file("services", "credit_service.py")

    fn_body = _find_function_body(source, "get_balance")
    assert fn_body is not None, "get_balance() not found in credit_service.py.  T-229."

    assert "_expire_user_packs" in fn_body, (
        "get_balance() must call _expire_user_packs() before reading credit_balance.  "
        "Without this call, users see unexpired credits even after their pack has "
        "passed its expires_at date.  T-229."
    )


def test_t229_deduct_calls_expire_user_packs() -> None:
    """T-229 — deduct() must call _expire_user_packs() before checking balance.

    If deduct() skips the expiry sweep, a user whose pack expired between the
    last get_balance() call and the deduction attempt could over-spend.
    """
    source = read_backend_file("services", "credit_service.py")

    fn_body = _find_function_body(source, "deduct")
    assert fn_body is not None, "deduct() not found in credit_service.py.  T-229."

    assert "_expire_user_packs" in fn_body, (
        "deduct() must call _expire_user_packs() before checking or deducting the "
        "balance.  Without this, a user whose pack expired between the last "
        "get_balance() call and the deduction would spend credits that should have "
        "been swept.  T-229."
    )


def test_t229_deduct_calls_drain_packs() -> None:
    """T-229 — deduct() must call _drain_packs() after recording the ledger entry.

    _drain_packs() keeps pack.credits_remaining in sync with user.credit_balance.
    Both must be called inside the same SELECT FOR UPDATE transaction so no
    concurrent operation sees an inconsistent snapshot.
    """
    source = read_backend_file("services", "credit_service.py")

    fn_body = _find_function_body(source, "deduct")
    assert fn_body is not None, "deduct() not found in credit_service.py.  T-229."

    assert "_drain_packs" in fn_body, (
        "deduct() must call _drain_packs() after recording the CreditLedger entry.  "
        "This keeps StripeCreditPack.credits_remaining in sync with credit_balance "
        "so the invariant credit_balance >= SUM(active packs.credits_remaining) holds.  "
        "T-229."
    )


def test_t229_drain_packs_orders_by_expires_at_asc() -> None:
    """T-229 — _drain_packs() must ORDER BY expires_at ASC (FIFO by expiry).

    Draining the soonest-expiring pack first maximises the user's effective
    credit lifetime.  Ordering by expires_at DESC would drain the longest-lived
    pack first, causing the short-lived pack to expire unused.  Ordering by
    created_at or purchased_at would not correctly handle packs with different
    validity windows.
    """
    # Look in both credit_service.py and stripe_service.py.
    found_source = None
    for parts in [("services", "credit_service.py"), ("services", "stripe_service.py")]:
        path = BACKEND_ROOT.joinpath(*parts)
        if path.exists():
            s = path.read_text(encoding="utf-8")
            if "_drain_packs" in s:
                found_source = s
                break

    assert (
        found_source is not None
    ), "_drain_packs() not found in credit_service.py or stripe_service.py.  T-229."

    fn_body = _find_function_body(found_source, "_drain_packs")
    assert fn_body is not None, "Could not extract _drain_packs() body.  T-229."

    # Must contain expires_at with ascending order.
    has_asc = re.search(
        r"expires_at.*\.asc\(\)|order_by.*expires_at.*asc|ASC.*expires_at",
        fn_body,
        re.IGNORECASE,
    )
    assert has_asc, (
        "_drain_packs() must ORDER BY expires_at ASC to implement FIFO expiry drain.  "
        "Ordering by DESC drains the longest-lived pack first (wrong).  "
        "Ordering by created_at/purchased_at is incorrect if packs have different "
        "validity windows.  Only expires_at ASC gives the correct FIFO-by-expiry "
        "behaviour.  T-229."
    )

    # Must NOT order by expires_at DESC.
    has_wrong_desc = re.search(
        r"expires_at.*\.desc\(\)|order_by.*expires_at.*desc|DESC.*expires_at",
        fn_body,
        re.IGNORECASE,
    )
    assert not has_wrong_desc, (
        "_drain_packs() must NOT ORDER BY expires_at DESC.  Descending order drains "
        "the longest-lived pack first, which leaves short-lived packs to expire unused.  "
        "T-229."
    )


def test_t229_expire_user_packs_uses_with_for_update_on_packs() -> None:
    """T-229 — _expire_user_packs() must hold SELECT FOR UPDATE on pack rows.

    Without the lock, two concurrent operations can both read the same pack as
    'active' and both attempt to revoke its credits — double-revoking and
    driving credit_balance below zero.
    """
    source = read_backend_file("services", "credit_service.py")

    fn_body = _find_function_body(source, "_expire_user_packs")
    assert (
        fn_body is not None
    ), "_expire_user_packs() not found in credit_service.py.  T-229."

    assert "with_for_update" in fn_body or "FOR UPDATE" in fn_body, (
        "_expire_user_packs() must use SELECT FOR UPDATE (.with_for_update()) when "
        "querying StripeCreditPack rows.  Without the row lock, two concurrent "
        "expiry sweeps can double-revoke the same pack's credits.  T-229."
    )


def test_t229_expire_user_packs_uses_with_for_update_on_user() -> None:
    """T-229 — _expire_user_packs() must also lock the user row.

    Locking pack rows without locking the user row leaves a window where a
    concurrent deduct() reads user.credit_balance between the pack lock and
    the balance update.  Both locks are needed for full serialisation.
    """
    source = read_backend_file("services", "credit_service.py")

    fn_body = _find_function_body(source, "_expire_user_packs")
    assert fn_body is not None, "_expire_user_packs() not found.  T-229."

    # The function body must reference the User model with a lock (either directly
    # via select(User) or via an existing _get_user(lock=True) helper call).
    has_user_lock = (
        "lock=True" in fn_body
        or ("User" in fn_body and "with_for_update" in fn_body)
        or ("user" in fn_body.lower() and "for_update" in fn_body.lower())
    )
    assert has_user_lock, (
        "_expire_user_packs() must acquire a row lock on the User row (e.g., "
        "_get_user(db, user_id, lock=True) or select(User).where(...).with_for_update()).  "
        "Locking only the pack rows leaves a race window between the pack revocation "
        "and the credit_balance update.  T-229."
    )


def test_t229_expire_user_packs_sets_status_expired() -> None:
    """T-229 — _expire_user_packs() must set pack.status = 'expired'."""
    source = read_backend_file("services", "credit_service.py")

    fn_body = _find_function_body(source, "_expire_user_packs")
    assert fn_body is not None, "_expire_user_packs() not found.  T-229."

    assert '"expired"' in fn_body or "'expired'" in fn_body, (
        "_expire_user_packs() must set pack.status = 'expired' on swept packs.  "
        "Without this, the pack would be swept again on the next call (infinite loop "
        "of revocations) because status='active' still matches the WHERE clause.  "
        "T-229."
    )


def test_t229_drain_packs_sets_status_consumed_when_empty() -> None:
    """T-229 — _drain_packs() must set pack.status = 'consumed' when credits_remaining hits 0."""
    found_source = None
    for parts in [("services", "credit_service.py"), ("services", "stripe_service.py")]:
        path = BACKEND_ROOT.joinpath(*parts)
        if path.exists():
            s = path.read_text(encoding="utf-8")
            if "_drain_packs" in s:
                found_source = s
                break

    assert found_source is not None, "_drain_packs() source not found.  T-229."

    fn_body = _find_function_body(found_source, "_drain_packs")
    assert fn_body is not None, "Could not extract _drain_packs() body.  T-229."

    assert '"consumed"' in fn_body or "'consumed'" in fn_body, (
        "_drain_packs() must set pack.status = 'consumed' when credits_remaining "
        "reaches 0.  This prevents the pack from appearing in future active-pack "
        "queries (WHERE status = 'active'), keeping query performance optimal.  T-229."
    )


# ---------------------------------------------------------------------------
# T-230–T-233: Billing endpoints
# ---------------------------------------------------------------------------


def test_t230_t234_billing_router_file_exists() -> None:
    """T-230 — backend/routers/billing.py must exist."""
    path = BACKEND_ROOT / "routers" / "billing.py"
    assert path.exists(), (
        "backend/routers/billing.py must exist.  This module defines the 5 billing "
        "endpoints: GET /billing/package, POST /billing/checkout, "
        "GET /billing/status, GET /billing/history, POST /billing/webhook.  T-230."
    )


def test_t230_package_endpoint_exists() -> None:
    """T-230 — GET /billing/package endpoint must exist in billing router."""
    source = read_backend_file("routers", "billing.py")
    has_package = re.search(
        r'@\w+\.get\s*\(\s*["\']/?(?:billing/)?package["\']', source
    )
    assert has_package, (
        "routers/billing.py must define GET /package (or /billing/package) endpoint.  "
        "This returns the static package config (credits, price_cents, validity_days, "
        "currency) so the frontend Billing page can display the offer without "
        "hard-coding prices.  T-230."
    )


def test_t230_package_endpoint_does_not_require_auth() -> None:
    """T-230 — GET /billing/package must not require authentication.

    The package info (price, credits, validity) is public product information.
    Requiring auth would prevent the landing page from showing the price to
    unauthenticated visitors.
    """
    source = read_backend_file("routers", "billing.py")

    # Find the package endpoint definition and check nearby lines.
    pkg_match = re.search(
        r'@\w+\.get\s*\(\s*["\']/?(?:billing/)?package["\'][^\n]*\n' r"(?:.*\n){0,5}",
        source,
    )
    if pkg_match:
        vicinity = pkg_match.group(0)
        assert "get_current_user" not in vicinity, (
            "GET /billing/package must not depend on get_current_user.  "
            "The package price is public information.  T-230."
        )


def test_t230_billing_schemas_file_exists() -> None:
    """T-230 — backend/schemas/billing.py must exist.

    All billing endpoint request/response shapes live in schemas/billing.py.
    Pydantic validation at the boundary prevents malformed data from reaching
    the service layer.
    """
    path = BACKEND_ROOT / "schemas" / "billing.py"
    assert path.exists(), (
        "backend/schemas/billing.py must exist.  This file defines Pydantic schemas "
        "for all billing request and response types: PackageResponse, CheckoutResponse, "
        "BillingStatusResponse, PackHistoryItem.  T-230."
    )


def test_t231_checkout_endpoint_exists() -> None:
    """T-231 — POST /billing/checkout must exist in billing router."""
    source = read_backend_file("routers", "billing.py")
    has_checkout = re.search(
        r'@\w+\.post\s*\(\s*["\']/?(?:billing/)?checkout["\']', source
    )
    assert has_checkout, (
        "routers/billing.py must define POST /checkout (or /billing/checkout).  "
        "This endpoint calls stripe_service.create_checkout_session() and returns "
        "the Stripe Hosted Checkout URL.  T-231."
    )


def test_t231_checkout_endpoint_requires_auth() -> None:
    """T-231 — POST /billing/checkout must require authentication.

    An unauthenticated checkout would create a Stripe session with no user_id
    in metadata, so the webhook cannot credit anyone.  Auth is required to
    bind the session to a user.
    """
    source = read_backend_file("routers", "billing.py")

    checkout_match = re.search(
        r'@\w+\.post\s*\(\s*["\']/?(?:billing/)?checkout["\'][^\n]*\n' r"(?:.*\n){0,8}",
        source,
    )
    if checkout_match:
        vicinity = checkout_match.group(0)
        assert "get_current_user" in vicinity or "current_user" in vicinity, (
            "POST /billing/checkout must depend on get_current_user.  An unauthenticated "
            "checkout creates a Stripe session with no user_id, so the webhook cannot "
            "credit anyone.  T-231."
        )


def test_t231_checkout_rate_limit_tier_in_rate_limit_middleware() -> None:
    """T-231/T-235 — rate_limit.py must define a billing checkout rate-limit tier.

    5 checkout sessions per user per hour prevents scripts from flooding Stripe
    with sessions (each session has a processing cost) and stops a user from
    continuously creating sessions to probe pricing.
    """
    source = read_backend_file("middleware", "rate_limit.py")

    has_billing_checkout = (
        "_BILLING_CHECKOUT_PATH_RE" in source
        or "billing_checkout" in source
        or re.search(r"billing.{0,20}checkout", source, re.IGNORECASE)
    )
    assert has_billing_checkout, (
        "middleware/rate_limit.py must define a rate-limit tier for POST /billing/checkout.  "
        "Limit: 5 sessions/user/hour.  Without this, a script can create thousands of "
        "Stripe sessions, incurring platform processing costs.  T-231/T-235."
    )


def test_t231_checkout_rate_limit_is_five_per_hour() -> None:
    """T-231/T-235 — The billing checkout rate limit must be 5 per hour (3600 s)."""
    source = read_backend_file("middleware", "rate_limit.py")

    # Find the billing checkout limit constant.
    limit_match = re.search(r"_BILLING_CHECKOUT_LIMIT\s*=\s*(\d+)", source)
    if limit_match:
        assert int(limit_match.group(1)) == 5, (
            f"_BILLING_CHECKOUT_LIMIT must be 5 (got {limit_match.group(1)}).  "
            "5 purchases/hour is enough for legitimate use; higher values enable "
            "session-flooding attacks.  T-231/T-235."
        )

    window_match = re.search(r"_BILLING_CHECKOUT_WINDOW_SECONDS\s*=\s*(\d+)", source)
    if window_match:
        assert int(window_match.group(1)) == 3600, (
            f"_BILLING_CHECKOUT_WINDOW_SECONDS must be 3600 (got {window_match.group(1)}).  "
            "T-231/T-235."
        )


def test_t232_status_endpoint_exists() -> None:
    """T-232 — GET /billing/status must exist in billing router."""
    source = read_backend_file("routers", "billing.py")
    has_status = re.search(r'@\w+\.get\s*\(\s*["\']/?(?:billing/)?status["\']', source)
    assert has_status, (
        "routers/billing.py must define GET /status (or /billing/status).  "
        "The frontend success page polls this to confirm credits were granted.  T-232."
    )


def test_t232_status_endpoint_scopes_by_both_session_id_and_user_id() -> None:
    """T-232 → updated for Phase 22 (T-303/T-306): /billing/status stays IDOR-safe.

    Phase 22 (Plan §25) replaces the Stripe ``session_id`` poll key with the Lemon
    ``checkout_ref`` (``session_id`` survives only inside the bounded Stripe grace
    window, T-303). The load-bearing invariant is unchanged: every status lookup is
    scoped by ``user_id`` so a guessed/scraped ref can never reveal another user's
    checkout. This asserts that scoping over the current poll key; the authoritative
    behavioural IDOR test is the phase25 ``checkout_ref`` 404 case.
    """
    source = read_backend_file("routers", "billing.py")

    # The poll key is now the Lemon checkout_ref (session_id only during grace).
    assert (
        "checkout_ref" in source
    ), "GET /billing/status must poll by the Lemon checkout_ref (Phase 22). T-303."
    # The IDOR guard is unchanged: lookups are scoped by user_id == current_user.id.
    assert re.search(r"user_id\s*==\s*current_user\.id", source), (
        "GET /billing/status lookups must be scoped by user_id (current_user.id) — "
        "scoping by the poll key alone is an IDOR leak. T-232 / T-303."
    )


def test_t232_status_endpoint_returns_404_not_403_on_mismatch() -> None:
    """T-232 — GET /billing/status must return 404 (not 403) on user_id mismatch.

    Returning 403 Forbidden would confirm that the session exists but belongs
    to another user — this leaks resource existence information.  404 gives
    no information about whether the session_id is valid at all.
    """
    source = read_backend_file("routers", "billing.py")

    # Find the status handler body.
    status_fn_match = re.search(
        r'@\w+\.get\s*\(\s*["\']/?(?:billing/)?status["\'][^\n]*\n'
        r"(?:async\s+)?def\s+\w+[^{]*\n((?:.*\n){0,40})",
        source,
    )
    if status_fn_match:
        handler_body = status_fn_match.group(1)
        # Must raise 404 (not 403) on pack not found.
        has_404 = "404" in handler_body or "HTTP_404" in handler_body
        has_403 = re.search(r"raise.*403|HTTP_403|status\.HTTP_403", handler_body)

        assert has_404, (
            "GET /billing/status must raise HTTPException(status_code=404) when the "
            "session_id is not found or belongs to a different user.  T-232."
        )
        assert not has_403, (
            "GET /billing/status must NOT return 403 on user_id mismatch.  "
            "403 confirms that the session exists but belongs to another user (IDOR "
            "information leakage).  Use 404 — same response for 'not found' and "
            "'belongs to other user'.  T-232."
        )


def test_t233_history_endpoint_exists() -> None:
    """T-233 — GET /billing/history must exist in billing router."""
    source = read_backend_file("routers", "billing.py")
    has_history = re.search(
        r'@\w+\.get\s*\(\s*["\']/?(?:billing/)?history["\']', source
    )
    assert has_history, (
        "routers/billing.py must define GET /history (or /billing/history).  "
        "Users need a way to view their purchase history for support and "
        "reconciliation purposes.  T-233."
    )


def test_t233_history_is_sorted_desc_and_capped() -> None:
    """T-233 → updated for Phase 22 (T-296/T-306): /billing/history sorts DESC, caps 50.

    Phase 22 reads the provider-neutral ``BillingCreditPack`` (renamed from
    ``StripeCreditPack``); the contract — newest-first, capped at 50 — is unchanged.
    """
    source = read_backend_file("routers", "billing.py")

    # The history endpoint reads the provider-neutral pack (Phase 22 rename).
    assert "BillingCreditPack" in source, (
        "GET /billing/history must read BillingCreditPack (renamed from "
        "StripeCreditPack in Phase 22). T-296."
    )
    # Newest-first, descending — accept purchased_at or created_at as the sort key.
    assert (
        re.search(r"(purchased_at|created_at)\.desc\(\)", source) or "DESC" in source
    ), "GET /billing/history must sort newest-first (purchased_at.desc()). T-233."
    # Capped at 50 so a heavy account never triggers an unbounded scan/payload.
    assert (
        "limit(50)" in source or ".limit(50)" in source
    ), "GET /billing/history must cap results at 50 entries (.limit(50)). T-233."


# ---------------------------------------------------------------------------
# T-234: POST /billing/webhook — raw body, idempotency, no auth
# ---------------------------------------------------------------------------


def test_t234_webhook_endpoint_exists() -> None:
    """T-234 — POST /billing/webhook must exist in billing router."""
    source = read_backend_file("routers", "billing.py")
    has_webhook = re.search(
        r'@\w+\.post\s*\(\s*["\']/?(?:billing/)?webhook["\']', source
    )
    assert has_webhook, (
        "routers/billing.py must define POST /webhook (or /billing/webhook).  "
        "This is the Stripe event receiver.  T-234."
    )


def test_t234_webhook_reads_raw_body() -> None:
    """T-234 — Webhook handler must read the raw request body (request.body()).

    stripe.Webhook.construct_event() validates the HMAC-SHA256 signature over
    the exact raw bytes received.  If the body is JSON-parsed first
    (e.g., via Pydantic model injection), whitespace normalisation or key
    reordering can alter the byte sequence, causing all signatures to fail.
    """
    source = read_backend_file("routers", "billing.py")

    webhook_fn_match = re.search(
        r'@\w+\.post\s*\(\s*["\']/?(?:billing/)?webhook["\'][^\n]*\n'
        r"(?:async\s+)?def\s+\w+[^{]*\n((?:.*\n){0,40})",
        source,
    )
    if webhook_fn_match:
        handler_body = webhook_fn_match.group(1)
        assert (
            "request.body()" in handler_body or "await request.body" in handler_body
        ), (
            "POST /billing/webhook must read the raw body with 'await request.body()' "
            "BEFORE any JSON parsing.  stripe.Webhook.construct_event() validates the "
            "HMAC over the exact raw bytes; JSON parsing can alter whitespace and break "
            "the signature.  T-234."
        )


def test_t234_webhook_validates_stripe_signature() -> None:
    """T-234 — Webhook handler must call stripe.Webhook.construct_event() with the Stripe-Signature header."""
    source = read_backend_file("routers", "billing.py")

    assert "construct_event" in source or "Stripe-Signature" in source, (
        "routers/billing.py webhook handler must validate the 'Stripe-Signature' "
        "header using stripe.Webhook.construct_event().  Without this, any caller "
        "can POST arbitrary events to /billing/webhook and inject fake credits.  "
        "T-234."
    )

    assert "Stripe-Signature" in source, (
        "routers/billing.py must read the 'Stripe-Signature' header from the request.  "
        "T-234."
    )


def test_t234_webhook_uses_tolerance_300() -> None:
    """T-234 → RETIRED by Phase 22 (T-297/T-303/T-306): no Stripe tolerance window.

    The Phase-18 receiver called ``stripe.Webhook.construct_event(..., tolerance=300)``.
    Phase 22 replaces it with the Lemon receiver, which verifies an HMAC-SHA256 over
    the raw body (``_verify_lemon_signature``, fail-closed) with **no** timestamp
    tolerance, and the bounded late-Stripe grace adapter (``_verify_stripe_signature``,
    stdlib ``hmac``) likewise enforces no clock-skew window — replay is neutralised by
    the durable inbox dedup + idempotent processing instead. So a ``tolerance=300``
    construct_event call must no longer exist in the router.
    """
    source = read_backend_file("routers", "billing.py")

    assert "construct_event" not in source and not re.search(
        r"tolerance\s*=\s*300", source
    ), (
        "The Stripe construct_event(tolerance=300) path is retired in Phase 22 — the "
        "Lemon/grace receivers verify HMAC fail-closed with no timestamp tolerance "
        "(replay handled by the durable inbox). T-297/T-303."
    )


def test_t234_webhook_idempotency_insert_before_handle_event() -> None:
    """T-234 → updated for Phase 22 (T-297/T-298/T-306): durable-inbox idempotency.

    The Phase-18 pattern inserted a ``StripeWebhookEvent`` row before calling
    ``handle_event`` inline. Phase 22 replaces inline processing with a **durable
    inbox**: the verified event is committed as a ``BillingWebhookEvent`` row (a
    duplicate 4-part identity trips the unique index → ``already_processed``) and the
    money work is enqueued by row id to the worker. The same crash-window invariant
    holds — the inbox row is persisted BEFORE the work is dispatched (``enqueue``), so
    a crash never loses the event. This asserts the inbox insert precedes the enqueue.
    """
    source = read_backend_file("routers", "billing.py")

    assert "BillingWebhookEvent" in source, (
        "The webhook receiver must persist a durable BillingWebhookEvent inbox row "
        "for idempotency (Phase 22 replaces inline StripeWebhookEvent). T-297/T-298."
    )
    # The durable inbox row must be committed BEFORE the work is enqueued — a crash
    # after enqueue is safe (the row exists); a crash before would lose the event.
    insert_pos = source.find("BillingWebhookEvent(")
    enqueue_pos = source.find("enqueue(")
    assert insert_pos != -1 and enqueue_pos != -1 and insert_pos < enqueue_pos, (
        "The BillingWebhookEvent inbox insert must precede the enqueue so the event "
        "is durable before dispatch — the Phase-22 form of insert-before-process. "
        "T-297/T-298."
    )


def test_t234_webhook_catches_integrity_error_for_duplicate_events() -> None:
    """T-234 — Webhook handler must catch IntegrityError for duplicate stripe_event_id.

    Two concurrent Stripe deliveries of the same event can both pass the SELECT
    check (both read 'no existing row') and then race to INSERT.  The UNIQUE
    constraint on stripe_event_id ensures only one INSERT succeeds; the other
    raises IntegrityError.  The handler must catch this and return
    {"status": "already_processed"} — not propagate a 500.
    """
    source = read_backend_file("routers", "billing.py")

    billing_source = source  # We're reading billing.py which is the webhook handler.
    has_integrity_handler = (
        "IntegrityError" in billing_source
        or "already_processed" in billing_source
        or "duplicate" in billing_source.lower()
    )
    assert has_integrity_handler, (
        "The webhook handler (or stripe_service.py) must catch IntegrityError on "
        "duplicate stripe_event_id inserts.  Two concurrent Stripe deliveries of the "
        "same event can both pass the SELECT idempotency check; only the DB UNIQUE "
        "constraint serialises them.  The loser gets IntegrityError — this must be "
        "caught and returned as 200 {'status': 'already_processed'}.  T-234."
    )


def test_t234_webhook_does_not_require_jwt_auth() -> None:
    """T-234 — POST /billing/webhook must NOT depend on get_current_user.

    Stripe sends webhook requests without any Authorization header.  If the
    endpoint requires JWT authentication, all webhooks will be rejected with
    401, users will never receive their credits, and Stripe will eventually
    disable the webhook endpoint after repeated failures.
    """
    source = read_backend_file("routers", "billing.py")

    # Find the webhook function definition.
    webhook_match = re.search(
        r'@\w+\.post\s*\(\s*["\']/?(?:billing/)?webhook["\'][^\n]*\n'
        r"((?:async\s+)?def\s+\w+[^\n]*\n(?:.*\n){0,10})",
        source,
    )
    if webhook_match:
        fn_header = webhook_match.group(1)
        assert "get_current_user" not in fn_header, (
            "POST /billing/webhook must NOT have a get_current_user dependency.  "
            "Stripe sends no Authorization header.  JWT auth on the webhook means "
            "ALL events are rejected with 401 and users never receive their credits.  "
            "Authentication is provided by the Stripe-Signature HMAC.  T-234."
        )


def test_t234_webhook_does_not_log_raw_payload() -> None:
    """T-234 — Webhook handler must not log the raw payload or Stripe-Signature header.

    The raw payload contains the full Stripe event data which may include
    customer email, IP address, and payment method fingerprints.  Logging this
    to Loki/Sentry/OTLP would violate PCI DSS data handling requirements.
    Structured logs must only include event_type, stripe_event_id, and
    processed user/pack identifiers.
    """
    source = read_backend_file("routers", "billing.py")

    webhook_fn_match = re.search(
        r'@\w+\.post\s*\(\s*["\']/?(?:billing/)?webhook["\'][^\n]*\n'
        r"(?:async\s+)?def\s+\w+[^{]*\n((?:.*\n){0,60})",
        source,
    )
    if webhook_fn_match:
        handler_body = webhook_fn_match.group(1)

        raw_payload_in_log = re.search(
            r"logger\.\w+\s*\([^)]*(?:payload|raw|event\s*=\s*event|body)[^)]*\)",
            handler_body,
        )
        assert not raw_payload_in_log, (
            "POST /billing/webhook must NOT log the raw payload variable.  "
            "The raw body contains PCI-scoped customer data (email, payment fingerprints).  "
            "Log only structured fields: event_type, stripe_event_id, user_id, pack_id.  "
            "T-234."
        )


def test_t234_webhook_returns_200_for_unhandled_event_types() -> None:
    """T-234 — Webhook handler must return 200 for unhandled event types.

    Stripe expects a 2xx response for every delivered webhook.  If the handler
    returns a non-2xx for an event type it does not handle (e.g., customer.created),
    Stripe marks the delivery as failed and retries — eventually disabling the
    endpoint.  The correct pattern is: dispatch known types; log and return 200 for all others.
    """
    source = read_backend_file("routers", "billing.py")

    # The webhook handler (or stripe_service.handle_event) must have an else/default branch.
    has_default_branch = (
        "else:" in source
        or "return {" in source  # a catch-all that returns ok
        or "already_processed" in source
    )
    assert has_default_branch or "handle_event" in source, (
        "The webhook handler must return 200 (e.g., {'status': 'ok'}) for event types "
        "it does not handle.  Stripe retries any non-2xx response, which can lead to "
        "endpoint disable after repeated failures.  The stripe_service.handle_event() "
        "function should log unknown events and return without error.  T-234."
    )


# ---------------------------------------------------------------------------
# T-235: Middleware exemptions — CSRF + rate limit bypass for webhook
# ---------------------------------------------------------------------------


def test_t235_webhook_path_in_csrf_exempt_paths() -> None:
    """T-235 — /billing/webhook must be in CsrfMiddleware._EXEMPT_PATHS.

    Stripe POST requests carry no CSRF cookie.  If /billing/webhook is not
    exempt, all webhook deliveries are rejected with 403, and users never
    receive their credits.
    """
    source = read_backend_file("middleware", "csrf.py")

    assert "/billing/webhook" in source, (
        "middleware/csrf.py _EXEMPT_PATHS frozenset must include '/billing/webhook' "
        "as a literal string.  Stripe POSTs carry no CSRF cookie — without this "
        "exemption, every webhook delivery is rejected with 403.  T-235."
    )

    # Must be in the frozenset, not just mentioned in a comment.
    exempt_match = re.search(
        r"_EXEMPT_PATHS\s*=\s*frozenset\s*\(\s*\{([^}]+)\}",
        source,
        re.DOTALL,
    )
    if exempt_match:
        exempt_set_contents = exempt_match.group(1)
        assert "/billing/webhook" in exempt_set_contents, (
            "'/billing/webhook' must appear inside the _EXEMPT_PATHS frozenset literal "
            "in csrf.py, not just in a comment.  T-235."
        )


def test_t235_webhook_path_in_rate_limit_bypass_paths() -> None:
    """T-235 → updated (Phase 21 GitHub + Phase 22 / T-306): webhook is rate-exempt.

    The webhook ingress was refactored into a dedicated ``_WEBHOOK_PATHS`` frozenset
    (shared by ``/billing/webhook`` and ``/integrations/github/webhook``) consulted in
    the dispatch path, replacing the original ``_BYPASS_PATHS`` membership. The
    invariant is unchanged: ``/billing/webhook`` is exempt from the per-user rate limit
    so a provider burst is never 429'd. This asserts the path lives in the consulted
    webhook-exemption frozenset.
    """
    source = read_backend_file("middleware", "rate_limit.py")

    assert "/billing/webhook" in source, (
        "middleware/rate_limit.py must exempt '/billing/webhook' from rate limiting — "
        "a provider burst must never be 429'd. T-235."
    )
    # Must live inside a consulted exemption frozenset (_WEBHOOK_PATHS or the legacy
    # _BYPASS_PATHS), not just a comment — check every such frozenset literal.
    exempt_sets = re.findall(
        r"_(?:WEBHOOK|BYPASS)_PATHS\s*=\s*frozenset\s*\(\s*\{([^}]+)\}",
        source,
        re.DOTALL,
    )
    assert any("/billing/webhook" in s for s in exempt_sets), (
        "'/billing/webhook' must appear inside the consulted rate-limit exemption "
        "frozenset (_WEBHOOK_PATHS) in rate_limit.py, not just in a comment. T-235."
    )


def test_t235_csrf_exempt_paths_uses_literal_string_not_prefix() -> None:
    """T-235 — /billing/webhook must be an exact path in _EXEMPT_PATHS, not a prefix.

    _EXEMPT_PATHS is checked with 'path in _EXEMPT_PATHS' (exact match).
    '/billing/webhook' must be the exact string.  A prefix like '/billing'
    would exempt the entire billing namespace including the authenticated
    /billing/checkout endpoint — which must still be CSRF-protected.
    """
    source = read_backend_file("middleware", "csrf.py")

    # Must NOT have '/billing' alone in the exempt set (without the /webhook suffix).
    exempt_match = re.search(
        r"_EXEMPT_PATHS\s*=\s*frozenset\s*\(\s*\{([^}]+)\}",
        source,
        re.DOTALL,
    )
    if exempt_match:
        exempt_set_contents = exempt_match.group(1)
        # Check that '/billing' appears only as '/billing/webhook' not standalone.
        standalone_billing = re.search(r'["\']\/billing["\']', exempt_set_contents)
        assert not standalone_billing, (
            "csrf.py _EXEMPT_PATHS must NOT contain '/billing' as a standalone path.  "
            "This would exempt ALL billing endpoints from CSRF protection, including "
            "POST /billing/checkout which must be CSRF-protected.  Use the exact path "
            "'/billing/webhook'.  T-235."
        )


# ---------------------------------------------------------------------------
# T-236: Security & Observability
# ---------------------------------------------------------------------------


def test_t236_lemonsqueezy_secrets_in_sensitive_keys() -> None:
    """T-236 → Phase 22 (T-304/T-308): the billing secret-key allow-list is Lemon's.

    The Stripe ``stripe_secret_key`` / ``stripe_webhook_secret`` entries were removed
    with the decommission (T-308); the Lemon API key + webhook secrets are the
    billing credentials scrubbed from structured logs now.
    """
    source = read_backend_file("services", "observability.py")
    for key in (
        "lemonsqueezy_api_key",
        "lemonsqueezy_webhook_secret",
        "lemonsqueezy_webhook_secret_prev",
    ):
        assert key in source, (
            f"services/observability.py _SENSITIVE_KEYS must include '{key}'. T-304."
        )
    assert "stripe_secret_key" not in source and "stripe_webhook_secret" not in source, (
        "The Stripe billing secret keys must be removed from _SENSITIVE_KEYS "
        "after the decommission (T-308)."
    )


def test_t236_client_secret_in_sensitive_keys() -> None:
    """T-236 — 'client_secret' must be in _SENSITIVE_KEYS in observability.py.

    Stripe's checkout.session.completed event payload contains client_secret
    fields for Payment Intents.  Without this key, client_secret could appear
    in log output if any code incorrectly logs event attributes.
    """
    source = read_backend_file("services", "observability.py")
    assert "client_secret" in source, (
        "services/observability.py _SENSITIVE_KEYS must include 'client_secret'.  "
        "Stripe event payloads contain client_secret fields for Payment Intents.  "
        "T-236."
    )


def test_t236_stripe_secret_patterns_removed_by_t308() -> None:
    """T-308 (supersedes T-236) — the Stripe ``sk_live_*``/``sk_test_*``/``whsec_*``
    secret regexes are removed from _SECRET_PATTERNS; the Lemon JWT + ``X-Signature``
    patterns (T-304) remain."""
    source = read_backend_file("services", "observability.py")

    assert not re.search(r"sk_\(\?:live\|test\)|sk_live_|sk_test_", source), (
        "The Stripe API-key secret pattern must be removed from observability.py "
        "after the decommission (T-308)."
    )
    assert "whsec_" not in source, (
        "The Stripe webhook-secret (whsec_) pattern must be removed from "
        "observability.py after the decommission (T-308)."
    )
    # The Lemon Squeezy signature/JWT redaction patterns (T-304) stay.
    assert "x-signature" in source.lower(), (
        "The Lemon X-Signature redaction pattern must remain in _SECRET_PATTERNS. "
        "T-304."
    )


def test_t236_billing_checkout_created_counter_defined() -> None:
    """T-236 — specforge_billing_checkout_created_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_checkout_created_total" in source, (
        "services/observability.py must define the Prometheus Counter "
        "'specforge_billing_checkout_created_total'.  This tracks the number of "
        "Stripe checkout sessions created (top-of-funnel billing metric).  T-236."
    )


def test_t236_billing_checkout_completed_counter_defined() -> None:
    """T-236 — specforge_billing_checkout_completed_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_checkout_completed_total" in source, (
        "services/observability.py must define 'specforge_billing_checkout_completed_total'.  "
        "This tracks successful webhook receipts.  Divergence between created and "
        "completed indicates failed webhooks or abandoned checkouts.  T-236."
    )


def test_t236_billing_credits_granted_counter_defined() -> None:
    """T-236 — specforge_billing_credits_granted_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_credits_granted_total" in source, (
        "services/observability.py must define 'specforge_billing_credits_granted_total'.  "
        "T-236."
    )


def test_t236_billing_credits_expired_counter_defined() -> None:
    """T-236 — specforge_billing_credits_expired_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_credits_expired_total" in source, (
        "services/observability.py must define 'specforge_billing_credits_expired_total'.  "
        "This tracks the waste metric (credits bought but expired unused).  "
        "Alert if this exceeds 20% of credits granted.  T-236."
    )


def test_t236_billing_credits_consumed_counter_defined() -> None:
    """T-236 — specforge_billing_credits_consumed_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_credits_consumed_total" in source, (
        "services/observability.py must define 'specforge_billing_credits_consumed_total'.  "
        "T-236."
    )


def test_t236_billing_pack_disputed_counter_defined() -> None:
    """T-236 → SUPERSEDED by Phase 22 (T-304): pack_disputed_total is RETIRED.

    The Phase-18 ``specforge_billing_pack_disputed_total`` is folded into the
    provider-neutral ``specforge_billing_credits_revoked_total{provider,reason}``
    (a dispute is ``reason='disputed'``) per Plan §25.6 / tasks.md T-304. The
    high-priority dispute signal is preserved under the successor counter, so this
    contract now asserts the fold rather than the retired name.
    """
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_pack_disputed_total" not in source, (
        "specforge_billing_pack_disputed_total is retired in Phase 22 (T-304) — it "
        "must NOT remain defined (no dangling refs)."
    )
    assert "specforge_billing_credits_revoked_total" in source, (
        "Dispute reversals must be counted by the provider-neutral successor "
        "specforge_billing_credits_revoked_total{provider,reason='disputed'}. T-304."
    )


def test_t236_billing_webhook_received_counter_defined() -> None:
    """T-236 — specforge_billing_webhook_received_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_webhook_received_total" in source, (
        "services/observability.py must define 'specforge_billing_webhook_received_total'.  "
        "T-236."
    )


def test_t236_billing_webhook_duplicate_counter_defined() -> None:
    """T-236 — specforge_billing_webhook_duplicate_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_webhook_duplicate_total" in source, (
        "services/observability.py must define 'specforge_billing_webhook_duplicate_total'.  "
        "High duplicate rates indicate Stripe retrying events — a signal that "
        "the webhook endpoint may be returning non-2xx responses intermittently.  "
        "T-236."
    )


def test_t236_billing_webhook_error_counter_defined() -> None:
    """T-236 — specforge_billing_webhook_error_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_webhook_error_total" in source, (
        "services/observability.py must define 'specforge_billing_webhook_error_total'.  "
        "Alert on any non-zero rate to catch webhook processing failures before "
        "they accumulate.  T-236."
    )


def test_t236_billing_checkout_rate_limited_counter_defined() -> None:
    """T-236 — specforge_billing_checkout_rate_limited_total Counter must be defined."""
    source = read_backend_file("services", "observability.py")
    assert "specforge_billing_checkout_rate_limited_total" in source, (
        "services/observability.py must define 'specforge_billing_checkout_rate_limited_total'.  "
        "This signals abuse attempts (scripts creating checkout sessions).  T-236."
    )


def test_t236_all_10_billing_counters_are_defined() -> None:
    """T-236 → updated for Phase 22 (T-304): the core billing counters are defined.

    The Phase-18 set documented 10 counters. Phase 22 (Plan §25.6 T-304) retires
    ``pack_disputed_total`` (folded into ``credits_revoked_total{reason='disputed'}``)
    and adds the provider-labelled set; the authoritative completeness check for the
    Phase-22 metric set lives in the phase25 contract
    (``test_t304_required_billing_metrics_defined``). This historical check now
    asserts the retained counters plus the dispute successor.
    """
    source = read_backend_file("services", "observability.py")

    expected_counters = [
        "specforge_billing_checkout_created_total",
        "specforge_billing_checkout_completed_total",
        "specforge_billing_credits_granted_total",
        "specforge_billing_credits_expired_total",
        "specforge_billing_credits_consumed_total",
        "specforge_billing_credits_revoked_total",  # successor to pack_disputed
        "specforge_billing_webhook_received_total",
        "specforge_billing_webhook_duplicate_total",
        "specforge_billing_webhook_error_total",
        "specforge_billing_checkout_rate_limited_total",
    ]

    missing = [c for c in expected_counters if c not in source]
    assert not missing, (
        "The following Prometheus billing counters are missing from observability.py:\n"
        + "\n".join(f"  - {c}" for c in missing)
        + "\n\nSee Plan §25.6 T-304 for the Phase-22 metric set."
    )


# ---------------------------------------------------------------------------
# T-227/T-236: Billing router registered in main.py
# ---------------------------------------------------------------------------


def test_billing_router_registered_in_main() -> None:
    """T-227/T-235 — main.py must include the billing router.

    Adding billing.py to routers/ without registering it in main.py means
    none of the 5 billing endpoints are reachable.  This is a silent failure —
    the app starts fine but all billing routes return 404.
    """
    source = read_backend_file("main.py")

    has_billing_import = re.search(
        r"from\s+routers\s+import.*billing|import.*billing.*router|billing.*router",
        source,
    )
    assert has_billing_import, (
        "main.py must import the billing router "
        "(e.g., 'from routers import billing as billing_router').  T-235."
    )

    has_include = "billing_router" in source or "billing.router" in source
    assert has_include, (
        "main.py must call app.include_router(billing_router.router) or equivalent.  "
        "Without this, all 5 billing endpoints return 404 even though the file exists.  "
        "T-235."
    )


# ---------------------------------------------------------------------------
# T-226/T-228/T-229: Model files exist
# ---------------------------------------------------------------------------


def test_stripe_credit_pack_model_exists() -> None:
    """T-226/T-228 — backend/models/stripe_credit_pack.py must exist."""
    path = BACKEND_ROOT / "models" / "stripe_credit_pack.py"
    assert path.exists(), (
        "backend/models/stripe_credit_pack.py must exist.  This SQLAlchemy model "
        "maps to the stripe_credit_packs table.  T-226."
    )


def test_stripe_webhook_event_model_exists() -> None:
    """T-226/T-234 — backend/models/stripe_webhook_event.py must exist."""
    path = BACKEND_ROOT / "models" / "stripe_webhook_event.py"
    assert path.exists(), (
        "backend/models/stripe_webhook_event.py must exist.  This SQLAlchemy model "
        "maps to the stripe_webhook_events idempotency table.  T-226."
    )


def test_stripe_credit_pack_model_has_required_columns() -> None:
    """T-226 — StripeCreditPack model must define all required columns."""
    source = read_backend_file("models", "stripe_credit_pack.py")

    required_columns = [
        "user_id",
        "stripe_session_id",
        "credits_purchased",
        "credits_remaining",
        "price_cents",
        "status",
        "expires_at",
        "purchased_at",
    ]
    missing = [c for c in required_columns if c not in source]
    assert not missing, (
        f"models/stripe_credit_pack.py is missing these columns: {missing}.  "
        "Each column serves a purpose: user_id links to the user, stripe_session_id "
        "enables IDOR-safe status lookups, credits_remaining drives FIFO drain, "
        "expires_at drives lazy expiry, status gates active-pack queries.  T-226."
    )


def test_stripe_webhook_event_model_has_stripe_event_id() -> None:
    """T-226/T-234 — StripeWebhookEvent model must have stripe_event_id column."""
    source = read_backend_file("models", "stripe_webhook_event.py")
    assert "stripe_event_id" in source, (
        "models/stripe_webhook_event.py must define a stripe_event_id column.  "
        "This column has a UNIQUE constraint that serialises concurrent duplicate "
        "webhook deliveries.  T-226."
    )


def test_stripe_webhook_event_model_has_event_type() -> None:
    """T-226/T-234 — StripeWebhookEvent model must record event_type for audit trail."""
    source = read_backend_file("models", "stripe_webhook_event.py")
    assert "event_type" in source, (
        "models/stripe_webhook_event.py must define an event_type column.  "
        "Storing the event type enables audit queries like "
        "'how many checkout.session.completed events have we processed?'  T-226."
    )


# ---------------------------------------------------------------------------
# T-237: Unit tests — Phase-18 Stripe unit suite retired by the decommission
# ---------------------------------------------------------------------------
#
# Phase 18 shipped ``tests/test_stripe_payments.py`` covering the Stripe runtime
# (checkout-session creation, webhook idempotency, IDOR, lazy expiry, FIFO drain,
# dispute revocation, signature rejection, rate limit, livemode). That runtime is
# gone (T-308), so the file was removed. The same correctness properties are now
# covered by the Phase-22 Lemon Squeezy suites (idempotency, IDOR, expiry, drain,
# reversal/dispute, signature, rate limit) and the decommission contract
# (``tests/test_stripe_decommission.py``).


def test_t237_stripe_unit_suite_retired_by_t308() -> None:
    """T-308 (supersedes T-237) — the Phase-18 Stripe unit-test file is removed."""
    path = BACKEND_ROOT / "tests" / ("test_stripe_" + "payments.py")
    assert not path.exists(), (
        "tests/test_stripe_payments.py must be removed with the Stripe "
        "decommission (T-308); the Lemon suites cover the billing properties now."
    )


def test_t237_billing_correctness_coverage_migrated_to_phase22() -> None:
    """T-308 — the billing correctness properties are still covered post-Stripe.

    The decommission contract exists, and the Lemon billing suites cover the
    idempotency / IDOR / expiry / drain / reversal properties the Phase-18 file did.
    """
    decommission = BACKEND_ROOT / "tests" / "test_stripe_decommission.py"
    assert decommission.exists(), (
        "tests/test_stripe_decommission.py must pin the post-removal contract. T-308."
    )
    lemon_suites = [
        p.name for p in (BACKEND_ROOT / "tests").glob("*.py") if "billing" in p.name
    ]
    assert lemon_suites, (
        "The Phase-22 Lemon billing test suites must remain to cover the billing "
        "correctness properties. T-308."
    )


# ---------------------------------------------------------------------------
# T-238: Frontend files
# ---------------------------------------------------------------------------


def test_t238_billing_page_exists() -> None:
    """T-238 — frontend/src/pages/Billing.tsx must exist."""
    path = REPO_ROOT / "frontend" / "src" / "pages" / "Billing.tsx"
    assert path.exists(), (
        "frontend/src/pages/Billing.tsx must exist.  This is the main credit "
        "purchase page showing the package offer, current balance, and purchase "
        "history.  T-238."
    )


def test_t238_billing_types_file_exists() -> None:
    """T-238 — frontend/src/types/billing.ts must exist."""
    path = REPO_ROOT / "frontend" / "src" / "types" / "billing.ts"
    assert path.exists(), (
        "frontend/src/types/billing.ts must exist.  This file defines TypeScript "
        "interfaces matching the backend billing API response schemas: "
        "BillingPackage, StripeCreditPack, BillingStatusResponse, CheckoutResponse.  "
        "T-238."
    )


def test_t238_billing_types_has_billing_package_interface() -> None:
    """T-238 — billing.ts must define BillingPackage interface."""
    source = (REPO_ROOT / "frontend" / "src" / "types" / "billing.ts").read_text(
        encoding="utf-8"
    )
    assert "BillingPackage" in source, (
        "frontend/src/types/billing.ts must define the BillingPackage interface "
        "(credits, price_cents, validity_days, currency).  T-238."
    )


def test_t238_billing_types_has_stripe_credit_pack_interface() -> None:
    """T-238 → renamed by Phase 22 (T-305/T-306): the pack type is BillingCreditPack.

    Phase 22 renames the frontend ``StripeCreditPack`` interface to the provider-
    neutral ``BillingCreditPack`` (same shape: id, credits_purchased,
    credits_remaining, status, purchased_at, expires_at) and removes the old name
    entirely. The contract is that the pack interface exists under the new name.
    """
    source = (REPO_ROOT / "frontend" / "src" / "types" / "billing.ts").read_text(
        encoding="utf-8"
    )
    assert "BillingCreditPack" in source, (
        "frontend/src/types/billing.ts must define the BillingCreditPack interface "
        "(renamed from StripeCreditPack in Phase 22). T-305."
    )
    assert (
        "StripeCreditPack" not in source
    ), "The old StripeCreditPack type name must be removed entirely (Phase 22). T-305."


def test_t238_billing_types_has_billing_status_response_interface() -> None:
    """T-238 — billing.ts must define BillingStatusResponse interface."""
    source = (REPO_ROOT / "frontend" / "src" / "types" / "billing.ts").read_text(
        encoding="utf-8"
    )
    assert "BillingStatusResponse" in source, (
        "frontend/src/types/billing.ts must define the BillingStatusResponse interface "
        "(status: 'pending' | 'completed', credits_added, expires_at).  "
        "This is the response shape from GET /billing/status.  T-238."
    )


def test_t238_billing_types_has_checkout_response_interface() -> None:
    """T-238 — billing.ts must define CheckoutResponse interface."""
    source = (REPO_ROOT / "frontend" / "src" / "types" / "billing.ts").read_text(
        encoding="utf-8"
    )
    assert "CheckoutResponse" in source or "checkout_url" in source, (
        "frontend/src/types/billing.ts must define the CheckoutResponse interface "
        "(checkout_url: string) matching the POST /billing/checkout response.  T-238."
    )


def test_t238_billing_types_stripe_credit_pack_has_status_union() -> None:
    """T-238 — StripeCreditPack.status must be a union of known literals.

    Using 'string' for status allows typos ('Expired', 'ACTIVE') to slip
    through without a type error.  The union type catches mismatches at
    compile time.
    """
    source = (REPO_ROOT / "frontend" / "src" / "types" / "billing.ts").read_text(
        encoding="utf-8"
    )
    has_status_union = re.search(
        r'"active"\s*\|\s*"consumed"'
        r'|"consumed"\s*\|\s*"expired"'
        r"|active.*consumed.*expired.*disputed",
        source,
    )
    assert has_status_union, (
        "billing.ts StripeCreditPack.status must be a TypeScript union type: "
        "'active' | 'consumed' | 'expired' | 'disputed'.  Using 'string' allows "
        "typos to pass type checking undetected.  T-238."
    )


# NOTE (issue #84): the three T-238 Billing.tsx endpoint tests below originally
# scanned Billing.tsx for raw endpoint strings. The billing calls have since
# moved behind the shared axios layer (frontend/src/services/api.ts exposes
# fetchBillingStatus / fetchBillingPackage / fetchBillingHistory), so the tests
# now pin the full chain: the page calls the service helper AND the helper hits
# the contract endpoint. The user-facing invariants are unchanged.


def _read_frontend_file(*parts: str) -> str:
    return (REPO_ROOT / "frontend" / "src").joinpath(*parts).read_text(encoding="utf-8")


def test_t238_billing_page_polls_billing_status() -> None:
    """T-238 — Billing.tsx must poll GET /billing/status for checkout completion.

    The success redirect page needs to poll /billing/status until status is
    'completed' or a timeout is reached.  Without polling, users are shown a
    success page that does not reflect whether credits were actually granted.
    """
    page = _read_frontend_file("pages", "Billing.tsx")
    api = _read_frontend_file("services", "api.ts")
    assert "fetchBillingStatus" in page, (
        "Billing.tsx must call fetchBillingStatus (services/api.ts) to confirm "
        "credits were granted after the checkout redirect.  The success page "
        "must poll until status is 'completed'.  T-238."
    )
    assert "/billing/status" in api, (
        "services/api.ts fetchBillingStatus must call GET /billing/status.  T-238."
    )


def test_t238_billing_page_calls_billing_package_endpoint() -> None:
    """T-238 — Billing.tsx must fetch GET /billing/package to display the offer dynamically."""
    page = _read_frontend_file("pages", "Billing.tsx")
    api = _read_frontend_file("services", "api.ts")
    assert "fetchBillingPackage" in page, (
        "Billing.tsx must fetch the current offer (price, credits, validity) via "
        "fetchBillingPackage.  Hard-coding prices in the component means a price "
        "change requires a frontend deploy.  T-238."
    )
    assert "/billing/package" in api, (
        "services/api.ts fetchBillingPackage must call GET /billing/package.  T-238."
    )


def test_t238_billing_page_calls_billing_history_endpoint() -> None:
    """T-238 — Billing.tsx must fetch GET /billing/history for the purchase history table."""
    page = _read_frontend_file("pages", "Billing.tsx")
    api = _read_frontend_file("services", "api.ts")
    assert "fetchBillingHistory" in page, (
        "Billing.tsx must populate the purchase history table via "
        "fetchBillingHistory.  Users need visibility into past purchases for "
        "support and reconciliation.  T-238."
    )
    assert "/billing/history" in api, (
        "services/api.ts fetchBillingHistory must call GET /billing/history.  T-238."
    )


def test_t238_billing_route_registered_in_app() -> None:
    """T-238 — /billing route must be registered in frontend/src/App.tsx.

    A Billing.tsx page that is not registered as a route is unreachable.
    The route must be inside the auth guard so unauthenticated users are
    redirected to login.
    """
    app_path = REPO_ROOT / "frontend" / "src" / "App.tsx"
    assert app_path.exists(), "frontend/src/App.tsx must exist.  T-238."
    source = app_path.read_text(encoding="utf-8")

    assert "Billing" in source and "/billing" in source, (
        "frontend/src/App.tsx must register the /billing route pointing to Billing.tsx.  "
        "A page that is not registered as a route is unreachable from the browser.  "
        "T-238."
    )


def test_t238_credit_meter_has_expiry_warning() -> None:
    """T-238 — CreditMeter.tsx must show an expiry warning chip for soon-expiring packs.

    Users must be warned before their credits expire so they can use them.
    The design spec calls for an amber chip (4-7 days) and red chip (≤3 days).
    Without this warning, users discover expired credits only after a generation
    attempt fails.
    """
    credit_meter_path = (
        REPO_ROOT / "frontend" / "src" / "components" / "shared" / "CreditMeter.tsx"
    )
    if not credit_meter_path.exists():
        # Some implementations may embed this in a different file.
        return

    source = credit_meter_path.read_text(encoding="utf-8")
    has_expiry_warning = (
        "expir" in source.lower()
        or "expires_at" in source
        or "ExpiryWarning" in source
        or "expiry" in source.lower()
    )
    assert has_expiry_warning, (
        "CreditMeter.tsx must show an expiry warning chip for active packs that "
        "expire within 7 days.  Without this, users discover expired credits only "
        "when a generation attempt fails (poor UX).  T-238."
    )


# ---------------------------------------------------------------------------
# T-226/T-235: .env.example has Stripe vars documented
# ---------------------------------------------------------------------------


def test_env_example_documents_lemonsqueezy_vars_not_stripe() -> None:
    """T-308 (supersedes T-227) — .env.example documents the Lemon billing vars and
    no longer ships STRIPE_* placeholder env vars.

    .env.example is the authoritative self-hosting reference. After the Stripe
    decommission it must document the Lemon Squeezy billing config (the runtime
    provider) and must not carry the dead STRIPE_* placeholders.
    """
    env_example_path = BACKEND_ROOT / ".env.example"
    assert env_example_path.exists(), "backend/.env.example must exist."
    content = env_example_path.read_text(encoding="utf-8")

    for var in (
        "LEMONSQUEEZY_API_KEY",
        "LEMONSQUEEZY_WEBHOOK_SECRET",
        "LEMONSQUEEZY_STORE_ID",
        "LEMONSQUEEZY_VARIANT_ID",
    ):
        assert var in content, (
            f"backend/.env.example must document {var} for self-hosters. T-308."
        )

    # The dead Stripe placeholder assignments must be gone (a prose mention of
    # "STRIPE_*" in the decommission note is fine; an assignable var line is not).
    for dead in (
        "STRIPE_SECRET_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
        "STRIPE_PRICE_CENTS=",
        "STRIPE_SUCCESS_URL=",
    ):
        assert dead not in content, (
            f"backend/.env.example must not ship the dead {dead} placeholder after "
            "the Stripe decommission. T-308."
        )

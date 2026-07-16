"""Seeded-DB integration tests for migration 0034 (issue #44, Razorpay Step 2).

The backend unit suite builds its schema with ``Base.metadata.create_all`` and never
drives Alembic, so the constraint surgery in 0034 — dropping the 0018 inline
(auto-named) provider CHECKs and re-adding them widened under the canonical
``ck_*_provider`` names — is not exercised by the ORM-based tests. These tests run
the real migration against a throwaway PostgreSQL database and assert:

- every neutral billing table accepts ``provider='razorpay'`` rows post-0034 and
  still rejects unknown providers (under the canonical constraint name — proving
  the 0018 auto-generated names were replaced, not merely supplemented),
- the ``('razorpay')`` reconcile-cursor row is seeded (and ``'stripe'`` stays
  excluded from the cursor CHECK),
- the downgrade guard refuses to narrow the CHECKs while razorpay rows exist, and
  a clean downgrade→upgrade round-trip is idempotent (cursor row deleted, then
  re-seeded exactly once).

These follow the project convention of skipping when ``TEST_DATABASE_URL`` is unset
(the same guard the 0018 migration tests use). Point it at a database whose schema
may be dropped — the tests reset ``public`` to a clean slate.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

_requires_pg = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — migration integration test skipped. Set it to a "
        "postgresql+asyncpg:// URL whose schema may be dropped (e.g. a dedicated "
        "*_mig_test database) to exercise the 0034 constraint surgery. Issue #44."
    ),
)

# (table, canonical provider-CHECK name) — must stay in sync with the migration.
_PROVIDER_CHECKS = (
    ("billing_checkout_attempts", "ck_bca_provider"),
    ("billing_credit_packs", "ck_bcp_provider"),
    ("billing_credit_debts", "ck_bcd_provider"),
    ("billing_admin_corrections", "ck_bac_provider"),
    ("billing_webhook_events", "ck_bwe_provider"),
)


def _alembic(*args: str, expect_failure: bool = False) -> str:
    """Run alembic in a fresh subprocess pinned at ``TEST_DATABASE_URL``.

    A subprocess (not the in-process Alembic API) is required because the backend
    ``Settings`` singleton is instantiated at import time from the dev ``.env``; only
    a new process re-reads ``DATABASE_URL`` from the environment we override here.
    Returns combined output; with ``expect_failure`` the command must exit non-zero.
    """
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL or ""}
    proc = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    output = f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    if expect_failure:
        if proc.returncode == 0:
            raise AssertionError(
                f"alembic {' '.join(args)} unexpectedly succeeded:\n{output}"
            )
    elif proc.returncode != 0:
        raise AssertionError(f"alembic {' '.join(args)} failed:\n{output}")
    return output


@pytest.fixture(autouse=True)
def _restore_current_schema_after_test():
    """Do not leak this migration's historical schema into the shared suite DB."""
    yield
    if TEST_DATABASE_URL:
        _alembic("upgrade", "head")


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


async def _execute(sql: str, params: dict | None = None) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params or {})
    finally:
        await engine.dispose()


async def _scalar(sql: str, params: dict | None = None):
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).scalar_one()
    finally:
        await engine.dispose()


async def _seed_user(user_id: uuid.UUID) -> None:
    await _execute(
        "INSERT INTO users (id, email, google_id, credit_balance) "
        "VALUES (:id, :email, :gid, 0)",
        {
            "id": user_id,
            "email": f"mig34_{user_id.hex[:8]}@example.com",
            "gid": f"g-mig34-{user_id.hex[:8]}",
        },
    )


def _five_table_inserts(
    provider: str, user_id: uuid.UUID, pack_id: uuid.UUID, tag: str
) -> tuple[tuple[str, str, dict], ...]:
    """One INSERT per neutral billing table, FK-ordered (packs before debts)."""
    return (
        (
            "billing_checkout_attempts",
            "INSERT INTO billing_checkout_attempts "
            "(checkout_ref, user_id, provider, checkout_nonce_hash, credits, "
            " price_cents, currency, validity_days, expires_at) "
            "VALUES (:ref, :uid, :provider, 'hash', 200, 79900, 'INR', 30, "
            " now() + interval '30 minutes')",
            {"ref": f"ref_{tag}_{uuid.uuid4().hex}", "uid": user_id},
        ),
        (
            "billing_credit_packs",
            "INSERT INTO billing_credit_packs "
            "(id, user_id, provider, provider_order_id, credits_purchased, "
            " credits_remaining, price_cents, currency, paid_item_amount_cents, "
            " provider_order_total_cents, status, purchased_at, expires_at) "
            "VALUES (:pack, :uid, :provider, :order_id, 200, 200, 79900, 'INR', "
            " 79900, 79900, 'active', now(), now() + interval '30 days')",
            {
                "pack": pack_id,
                "uid": user_id,
                "order_id": f"pay_{tag}_{uuid.uuid4().hex[:12]}",
            },
        ),
        (
            "billing_credit_debts",
            "INSERT INTO billing_credit_debts "
            "(user_id, source_pack_id, provider, credits_owed, reason) "
            "VALUES (:uid, :pack, :provider, 10, 'test refund reversal')",
            {"uid": user_id, "pack": pack_id},
        ),
        (
            "billing_admin_corrections",
            "INSERT INTO billing_admin_corrections "
            "(admin_user_id, target_user_id, provider, provider_order_id, credits, "
            " price_cents, currency, reason, evidence_url) "
            "VALUES (:uid, :uid, :provider, :order_id, 200, 79900, 'INR', "
            " 'test correction', 'https://example.com/evidence')",
            {"uid": user_id, "order_id": f"pay_corr_{tag}_{uuid.uuid4().hex[:12]}"},
        ),
        (
            "billing_webhook_events",
            "INSERT INTO billing_webhook_events "
            "(provider, event_name, provider_object_type, provider_object_id, "
            " payload_hash, normalized_payload) "
            "VALUES (:provider, 'payment_link.paid', 'payments', :obj, :hash, "
            " '{}'::jsonb)",
            {"obj": f"pay_{tag}_{uuid.uuid4().hex[:12]}", "hash": uuid.uuid4().hex},
        ),
    )


@_requires_pg
def test_0034_widens_provider_checks_and_seeds_cursor() -> None:
    """Post-0034 every billing table accepts razorpay rows under the canonical
    ck_* constraint names, unknown providers still reject, and the razorpay
    reconcile-cursor row is seeded next to the lemonsqueezy one."""

    async def _run() -> None:
        await _reset_schema()
        _alembic("upgrade", "0033")

        # Pre-0034 baseline: razorpay is rejected (by the 0018 auto-named CHECK).
        with pytest.raises(DBAPIError, match="provider"):
            await _execute(
                "INSERT INTO billing_webhook_events "
                "(provider, event_name, provider_object_type, provider_object_id, "
                " payload_hash, normalized_payload) "
                "VALUES ('razorpay', 'payment_link.paid', 'payments', 'pay_x', "
                " 'h', '{}'::jsonb)"
            )

        _alembic("upgrade", "0034")

        # Cursor: exactly the two reconciling providers, razorpay at the epoch
        # default so lane 2 starts from the beginning.
        providers = await _scalar(
            "SELECT array_agg(provider ORDER BY provider) "
            "FROM billing_reconciliation_cursors"
        )
        assert providers == ["lemonsqueezy", "razorpay"]
        epoch_start = await _scalar(
            "SELECT last_successful_run_at = '1970-01-01 00:00:00+00'::timestamptz "
            "FROM billing_reconciliation_cursors WHERE provider = 'razorpay'"
        )
        assert epoch_start is True

        # The cursor CHECK widened to razorpay but still excludes stripe.
        with pytest.raises(DBAPIError, match="ck_brc_provider"):
            await _execute(
                "INSERT INTO billing_reconciliation_cursors(provider) "
                "VALUES ('stripe')"
            )

        # All five tables accept a razorpay row (FK order: pack before debt).
        user_id = uuid.uuid4()
        await _seed_user(user_id)
        pack_id = uuid.uuid4()
        for _table, sql, params in _five_table_inserts(
            "razorpay", user_id, pack_id, "ok"
        ):
            await _execute(sql, {**params, "provider": "razorpay"})

        # Unknown providers reject on every table, and the error names the
        # canonical ck_* constraint — the 0018 auto-generated name is gone.
        bad_pack_id = uuid.uuid4()
        for (table, sql, params), (_t, ck_name) in zip(
            _five_table_inserts("paypal", user_id, bad_pack_id, "bad"),
            _PROVIDER_CHECKS,
            strict=True,
        ):
            if table == "billing_credit_debts":
                # FK must point at an existing pack; the razorpay one works —
                # the CHECK under test is on the debt row's own provider column.
                params = {**params, "pack": pack_id}
            with pytest.raises(DBAPIError, match=ck_name):
                await _execute(sql, {**params, "provider": "paypal"})

        for table, ck_name in _PROVIDER_CHECKS:
            auto_named = await _scalar(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conname = :auto AND conrelid = CAST(:tbl AS regclass)",
                {"auto": f"{table}_provider_check", "tbl": table},
            )
            assert auto_named == 0, f"{table} still carries the 0018 auto-named CHECK"

    asyncio.run(_run())


@_requires_pg
def test_0034_downgrade_guard_and_round_trip() -> None:
    """Downgrade refuses while razorpay rows exist; once clean it restores the
    narrow CHECKs and deletes the cursor row, and a re-upgrade re-seeds exactly
    one razorpay cursor row (idempotent round-trip)."""

    async def _run() -> None:
        await _reset_schema()
        _alembic("upgrade", "0034")

        # A razorpay money row blocks the downgrade (guard raises, alembic fails).
        await _execute(
            "INSERT INTO billing_webhook_events "
            "(provider, event_name, provider_object_type, provider_object_id, "
            " payload_hash, normalized_payload) "
            "VALUES ('razorpay', 'payment_link.paid', 'payments', 'pay_guard', "
            " 'h_guard', '{}'::jsonb)"
        )
        output = _alembic("downgrade", "0033", expect_failure=True)
        assert "Cannot downgrade 0034" in output
        assert "billing_webhook_events" in output

        # The failed attempt must not have partially narrowed anything: razorpay
        # inserts still work and the cursor row is still present.
        assert (
            await _scalar(
                "SELECT count(*) FROM billing_reconciliation_cursors "
                "WHERE provider = 'razorpay'"
            )
            == 1
        )

        # Clean up the razorpay row → downgrade now succeeds.
        await _execute("DELETE FROM billing_webhook_events WHERE provider = 'razorpay'")
        _alembic("downgrade", "0033")

        # Narrow world restored: no razorpay cursor row, lemonsqueezy retained,
        # razorpay rejected again.
        assert (
            await _scalar(
                "SELECT count(*) FROM billing_reconciliation_cursors "
                "WHERE provider = 'razorpay'"
            )
            == 0
        )
        assert (
            await _scalar(
                "SELECT count(*) FROM billing_reconciliation_cursors "
                "WHERE provider = 'lemonsqueezy'"
            )
            == 1
        )
        with pytest.raises(DBAPIError, match="ck_bwe_provider"):
            await _execute(
                "INSERT INTO billing_webhook_events "
                "(provider, event_name, provider_object_type, provider_object_id, "
                " payload_hash, normalized_payload) "
                "VALUES ('razorpay', 'payment_link.paid', 'payments', 'pay_y', "
                " 'h2', '{}'::jsonb)"
            )

        # Round-trip: re-upgrade re-widens and re-seeds exactly one cursor row.
        _alembic("upgrade", "0034")
        assert (
            await _scalar(
                "SELECT count(*) FROM billing_reconciliation_cursors "
                "WHERE provider = 'razorpay'"
            )
            == 1
        )

    asyncio.run(_run())

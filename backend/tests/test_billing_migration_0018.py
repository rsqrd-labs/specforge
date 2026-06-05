"""Seeded-DB integration tests for migration 0018 (Phase 22 — T-290).

The backend unit suite builds its schema with ``Base.metadata.create_all`` and
never drives Alembic, so the *backfill* of legacy ``stripe_credit_packs`` rows into
``billing_credit_packs`` — the highest-risk part of T-290 — is not exercised by the
ORM-based tests. These tests run the real migration against a throwaway PostgreSQL
database and assert the contract the harness text-checks cannot:

- balance preservation (``users.credit_balance`` byte-identical post-backfill),
- per-status accounting (consumed/expired derived correctly; ``credits_revoked=0``
  for every backfilled row including ``disputed``; disputed refund columns set),
- idempotency: the ``ON CONFLICT (provider, provider_checkout_id) …`` guard makes a
  re-run a no-op, and a ``downgrade``→``upgrade`` round-trip leaves identical counts
  while the Stripe tables survive the downgrade.

These follow the project convention of skipping when ``TEST_DATABASE_URL`` is unset
(the same guard the Stripe integration tests use). Point it at a database whose
schema may be dropped — the tests reset ``public`` to a clean slate.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

_requires_pg = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — migration integration test skipped. Set it to a "
        "postgresql+asyncpg:// URL whose schema may be dropped (e.g. a dedicated "
        "*_mig_test database) to exercise the 0018 backfill. T-290."
    ),
)


def _alembic(*args: str) -> None:
    """Run alembic in a fresh subprocess pinned at ``TEST_DATABASE_URL``.

    A subprocess (not the in-process Alembic API) is required because the backend
    ``Settings`` singleton is instantiated at import time from the dev ``.env``; only
    a new process re-reads ``DATABASE_URL`` from the environment we override here.
    """
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL or ""}
    proc = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} failed:\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


# Four legacy packs, one per Stripe status, with distinct accounting shapes.
# (status, credits_purchased, credits_remaining, price_cents)
_SEED_PACKS = (
    ("active", 200, 150, 900),
    ("consumed", 200, 0, 900),
    ("expired", 200, 120, 900),
    ("disputed", 200, 0, 900),
)


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


async def _seed_legacy_packs(user_id: uuid.UUID) -> dict[str, str]:
    """Insert a user + one stripe pack per status; returns {status: session_id}."""
    sessions: dict[str, str] = {}
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, email, google_id, credit_balance) "
                    "VALUES (:id, :email, :gid, :bal)"
                ),
                {
                    "id": user_id,
                    "email": f"mig_{user_id.hex[:8]}@example.com",
                    "gid": f"g-mig-{user_id.hex[:8]}",
                    "bal": 270,
                },
            )
            for status, purchased, remaining, price in _SEED_PACKS:
                session_id = f"cs_test_{status}_{uuid.uuid4().hex}"
                sessions[status] = session_id
                await conn.execute(
                    text(
                        "INSERT INTO stripe_credit_packs "
                        "(user_id, stripe_session_id, stripe_payment_intent_id, "
                        " credits_purchased, credits_remaining, price_cents, status, "
                        " purchased_at, expires_at) "
                        "VALUES (:uid, :sid, :pi, :purchased, :remaining, "
                        " :price, :status, now(), now() + interval '30 days')"
                    ),
                    {
                        "uid": user_id,
                        "sid": session_id,
                        "pi": f"pi_{status}_{uuid.uuid4().hex}",
                        "purchased": purchased,
                        "remaining": remaining,
                        "price": price,
                        "status": status,
                    },
                )
    finally:
        await engine.dispose()
    return sessions


async def _fetchrow(sql: str, params: dict) -> dict:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(sql), params)).mappings().one()
            return dict(row)
    finally:
        await engine.dispose()


async def _scalar(sql: str, params: dict | None = None):
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).scalar_one()
    finally:
        await engine.dispose()


@_requires_pg
def test_t290_backfill_preserves_balance_and_accounting() -> None:
    """0018 backfill copies every Stripe pack with correct per-status accounting and
    leaves users.credit_balance untouched; disputed rows keep credits_revoked=0."""

    async def _run() -> None:
        await _reset_schema()
        _alembic("upgrade", "0017")

        user_id = uuid.uuid4()
        sessions = await _seed_legacy_packs(user_id)
        balance_before = await _scalar(
            "SELECT credit_balance FROM users WHERE id = :id", {"id": user_id}
        )

        _alembic("upgrade", "0018")

        # Every legacy pack is mirrored.
        n_legacy = await _scalar("SELECT count(*) FROM stripe_credit_packs", {})
        n_neutral = await _scalar(
            "SELECT count(*) FROM billing_credit_packs WHERE provider = 'stripe'", {}
        )
        assert n_legacy == n_neutral == len(_SEED_PACKS)

        # Balance is byte-identical — the backfill is an audit copy, never a write
        # back to users.credit_balance.
        balance_after = await _scalar(
            "SELECT credit_balance FROM users WHERE id = :id", {"id": user_id}
        )
        assert balance_after == balance_before == 270

        # active: consumed = purchased - remaining; nothing expired/revoked.
        active = await _fetchrow(
            "SELECT * FROM billing_credit_packs WHERE provider_checkout_id = :s",
            {"s": sessions["active"]},
        )
        assert active["credits_consumed"] == 50
        assert active["credits_expired"] == 0
        assert active["credits_revoked"] == 0
        assert active["currency"] == "USD"
        assert active["paid_item_amount_cents"] == 900
        assert active["provider_order_total_cents"] == 900
        assert active["provider_refunded_total_cents_seen"] == 0
        assert active["refunded_item_amount_cents_processed"] == 0
        assert active["provider_order_id"] is not None  # mapped from payment_intent

        # consumed: fully drained.
        consumed = await _fetchrow(
            "SELECT * FROM billing_credit_packs WHERE provider_checkout_id = :s",
            {"s": sessions["consumed"]},
        )
        assert consumed["credits_consumed"] == 200
        assert consumed["credits_expired"] == 0

        # expired: expired = purchased - remaining; consumed stays 0.
        expired = await _fetchrow(
            "SELECT * FROM billing_credit_packs WHERE provider_checkout_id = :s",
            {"s": sessions["expired"]},
        )
        assert expired["credits_expired"] == 80
        assert expired["credits_consumed"] == 0

        # disputed: revoke is NOT inferred from credits_remaining; refund columns set.
        disputed = await _fetchrow(
            "SELECT * FROM billing_credit_packs WHERE provider_checkout_id = :s",
            {"s": sessions["disputed"]},
        )
        assert disputed["credits_revoked"] == 0
        assert disputed["credits_consumed"] == 0
        assert disputed["credits_expired"] == 0
        assert disputed["provider_refunded_total_cents_seen"] == 900
        assert disputed["refunded_item_amount_cents_processed"] == 900
        assert disputed["status"] == "disputed"

    asyncio.run(_run())


@_requires_pg
def test_t290_backfill_idempotent_and_downgrade_keeps_stripe() -> None:
    """Re-running the backfill is a no-op (ON CONFLICT guard), and a
    downgrade→upgrade round-trip leaves identical counts while Stripe survives."""

    async def _run() -> None:
        await _reset_schema()
        _alembic("upgrade", "0017")
        user_id = uuid.uuid4()
        sessions = await _seed_legacy_packs(user_id)
        _alembic("upgrade", "0018")

        count_first = await _scalar("SELECT count(*) FROM billing_credit_packs", {})
        assert count_first == len(_SEED_PACKS)

        # Direct re-insert against an existing (provider, provider_checkout_id) is
        # swallowed by the partial-unique ON CONFLICT target — no duplicate pack.
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO billing_credit_packs "
                        "(user_id, provider, provider_checkout_id, provider_order_id, "
                        " credits_purchased, credits_remaining, price_cents, currency, "
                        " paid_item_amount_cents, provider_order_total_cents, status, "
                        " purchased_at, expires_at) "
                        "VALUES (:uid, 'stripe', :s, 'dup-order', 5, 5, 900, "
                        " 'USD', 900, 900, 'active', now(), now()) "
                        "ON CONFLICT (provider, provider_checkout_id) "
                        "WHERE provider_checkout_id IS NOT NULL DO NOTHING"
                    ),
                    {"uid": user_id, "s": sessions["active"]},
                )
        finally:
            await engine.dispose()
        count_after_dup = await _scalar("SELECT count(*) FROM billing_credit_packs", {})
        assert count_after_dup == count_first

        # Round-trip: downgrade drops the neutral tables but keeps the Stripe ones.
        _alembic("downgrade", "0017")
        assert (
            await _scalar("SELECT to_regclass('billing_credit_packs') IS NULL", {})
        ) is True
        stripe_survives = await _scalar(
            "SELECT to_regclass('stripe_credit_packs') IS NOT NULL", {}
        )
        assert stripe_survives is True
        assert await _scalar("SELECT count(*) FROM stripe_credit_packs", {}) == len(
            _SEED_PACKS
        )

        # Re-upgrade backfills the same source rows → identical neutral count.
        _alembic("upgrade", "0018")
        count_second = await _scalar("SELECT count(*) FROM billing_credit_packs", {})
        assert count_second == count_first

    asyncio.run(_run())

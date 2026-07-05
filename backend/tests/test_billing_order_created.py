"""Behavioural tests for `order_created` grant processing (Phase 22 — T-299).

The grant is the most security-sensitive money path in the phase: a forged
`user_id` must grant nothing, economics must come from the checkout-attempt
SNAPSHOT (never live config), and a redelivered order must never double-credit.
None of that can be exercised by the source-grep harness, so these are
real-Postgres integration tests gated on ``TEST_DATABASE_URL`` (mirroring
``test_billing_worker.py``): they skip locally and run in CI against the migrated
database (the ``billing_purchase:`` ledger-reason unique index lives in migration
0018, so we run against the migrated DB rather than ``create_all``).

``handle_order_created`` calls the module-level ``AsyncSessionLocal`` and the
``credit_service`` singleton directly; we point the former at a per-test NullPool
maker (loop-safety, as the worker suite does) and pin the Lemon store/variant/
test_mode config so the provider-side checklist terms are deterministic.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import CreditLedger, User
from models.billing_checkout_attempt import BillingCheckoutAttempt
from models.billing_credit_pack import BillingCreditPack
from models.billing_webhook_event import BillingWebhookEvent
from services import billing_worker

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason=(
            "TEST_DATABASE_URL not set — Postgres grant integration test skipped. "
            "Runs in CI against the migrated test database. T-299."
        ),
    ),
]

_STORE_ID = "55555"
_VARIANT_ID = "99999"
_TEST_MODE = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_maker(monkeypatch) -> async_sessionmaker:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(billing_worker, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()


@pytest.fixture
async def session(db_maker: async_sessionmaker) -> AsyncSession:
    async with db_maker() as db:
        yield db


@pytest.fixture(autouse=True)
def lemon_config(monkeypatch):
    """Pin the provider-side checklist config so validation is deterministic."""
    monkeypatch.setattr(settings, "lemonsqueezy_store_id", _STORE_ID)
    monkeypatch.setattr(settings, "lemonsqueezy_variant_id", _VARIANT_ID)
    monkeypatch.setattr(settings, "lemonsqueezy_test_mode", _TEST_MODE)
    yield


class _Tracker:
    """Tracks created row ids for teardown (shared dev DB safety)."""

    def __init__(self) -> None:
        self.users: list[UUID] = []
        self.webhooks: list[UUID] = []


@pytest.fixture
async def cleanup(session: AsyncSession):
    tracker = _Tracker()
    yield tracker
    if tracker.webhooks:
        await session.execute(
            delete(BillingWebhookEvent).where(
                BillingWebhookEvent.id.in_(tracker.webhooks)
            )
        )
    for uid in tracker.users:
        await session.execute(
            delete(BillingCreditPack).where(BillingCreditPack.user_id == uid)
        )
        await session.execute(delete(CreditLedger).where(CreditLedger.user_id == uid))
        await session.execute(
            delete(BillingCheckoutAttempt).where(BillingCheckoutAttempt.user_id == uid)
        )
        await session.execute(delete(User).where(User.id == uid))
    await session.commit()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


async def _make_user(session: AsyncSession, cleanup, *, balance: int = 0) -> User:
    u = User(
        email=f"order-created-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Order Created Tester",
        avatar_url=None,
        credit_balance=balance,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    cleanup.users.append(u.id)
    return u


async def _make_attempt(
    session: AsyncSession,
    user: User,
    nonce_hash: str,
    *,
    credits: int = 200,
    price_cents: int = 900,
    currency: str = "USD",
    validity_days: int = 30,
    status: str = "provider_created",
    provider_checkout_id: str | None = None,
) -> BillingCheckoutAttempt:
    attempt = BillingCheckoutAttempt(
        checkout_ref=f"ref_{uuid4().hex}",
        user_id=user.id,
        provider="lemonsqueezy",
        provider_checkout_id=provider_checkout_id,
        checkout_nonce_hash=nonce_hash,
        credits=credits,
        price_cents=price_cents,
        currency=currency,
        validity_days=validity_days,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt


def _payload(
    attempt: BillingCheckoutAttempt,
    nonce_hash: str,
    *,
    order_id: str,
    **overrides: Any,
) -> dict[str, Any]:
    """A valid sanitised order_created payload (mirrors T-297's normalised inbox).

    Note: NO checkout id is present — ownership is proven by checkout_ref + nonce.
    """
    base: dict[str, Any] = {
        "provider": "lemonsqueezy",
        "event_name": "order_created",
        "order_id": order_id,
        "store_id": int(_STORE_ID),
        "customer_id": 4242,
        "order_item_id": 7001,
        "product_id": 800,
        "variant_id": int(_VARIANT_ID),
        "status": "paid",
        "currency": attempt.currency,
        "test_mode": _TEST_MODE,
        "item_price_cents": attempt.price_cents,
        "order_subtotal_cents": attempt.price_cents,
        "order_total_cents": attempt.price_cents,
        "discount_total_cents": 0,
        "refunded": False,
        "refunded_amount_cents": 0,
        "created_at": "2026-06-06T10:00:00.000000Z",
        "updated_at": "2026-06-06T10:00:00.000000Z",
        "custom": {
            "user_id": str(attempt.user_id),
            "checkout_ref": attempt.checkout_ref,
            "checkout_nonce_hash_from_webhook": nonce_hash,
            "environment": "test",
            "credits": attempt.credits,
            "price_cents": attempt.price_cents,
            "currency": attempt.currency,
        },
    }
    custom_overrides = overrides.pop("custom", None)
    base.update(overrides)
    if custom_overrides:
        base["custom"].update(custom_overrides)
    return base


async def _make_webhook(
    session: AsyncSession, cleanup: _Tracker, payload: dict[str, Any]
) -> BillingWebhookEvent:
    row = BillingWebhookEvent(
        provider="lemonsqueezy",
        event_name="order_created",
        provider_object_type="orders",
        provider_object_id=payload["order_id"],
        payload_hash=hashlib.sha256(repr(payload).encode()).hexdigest(),
        status="received",
        normalized_payload=payload,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    cleanup.webhooks.append(row.id)
    return row


# Reads go through a FRESH session (column selects, never ORM identity-map objects)
# so a value committed by the handler's own session is always observed and no shared
# ORM object is left in an expired, un-awaitable state.


async def _balance(maker: async_sessionmaker, user_id: UUID) -> int:
    async with maker() as db:
        return await db.scalar(select(User.credit_balance).where(User.id == user_id))


async def _pack_count(maker: async_sessionmaker, user_id: UUID) -> int:
    async with maker() as db:
        rows = await db.execute(
            select(BillingCreditPack.id).where(BillingCreditPack.user_id == user_id)
        )
        return len(rows.scalars().all())


async def _wh_status(maker: async_sessionmaker, wid: UUID) -> str:
    async with maker() as db:
        return await db.scalar(
            select(BillingWebhookEvent.status).where(BillingWebhookEvent.id == wid)
        )


async def _pack_by_order(
    maker: async_sessionmaker, order_id: str
) -> BillingCreditPack | None:
    async with maker() as db:
        return await db.scalar(
            select(BillingCreditPack).where(
                BillingCreditPack.provider_order_id == order_id
            )
        )


async def _attempt_status(maker: async_sessionmaker, attempt_id: UUID) -> tuple:
    async with maker() as db:
        row = await db.execute(
            select(
                BillingCheckoutAttempt.status,
                BillingCheckoutAttempt.completed_at,
                BillingCheckoutAttempt.provider_order_id,
            ).where(BillingCheckoutAttempt.id == attempt_id)
        )
        return row.one()


async def _purchase_ledger_count(maker: async_sessionmaker, order_id: str) -> int:
    async with maker() as db:
        rows = await db.execute(
            select(CreditLedger.id).where(
                CreditLedger.reason == f"billing_purchase:lemonsqueezy:{order_id}"
            )
        )
        return len(rows.scalars().all())


async def _purchase_ledger_amount(maker: async_sessionmaker, order_id: str) -> int:
    async with maker() as db:
        return await db.scalar(
            select(CreditLedger.amount).where(
                CreditLedger.reason == f"billing_purchase:lemonsqueezy:{order_id}"
            )
        )


# ---------------------------------------------------------------------------
# Happy path + snapshot anchoring
# ---------------------------------------------------------------------------


async def test_grants_with_no_checkout_id_when_ref_and_nonce_match(
    session, db_maker, cleanup
) -> None:
    nonce_hash = hashlib.sha256(b"nonce-1").hexdigest()
    user = await _make_user(session, cleanup, balance=10)
    attempt = await _make_attempt(session, user, nonce_hash)
    credits, price_cents, currency = (
        attempt.credits,
        attempt.price_cents,
        attempt.currency,
    )
    user_id, attempt_id = user.id, attempt.id
    order_id = f"ord_{uuid4().hex[:10]}"
    webhook = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )
    wid = webhook.id

    await billing_worker.handle_order_created({}, str(wid))

    assert await _balance(db_maker, user_id) == 10 + credits

    pack = await _pack_by_order(db_maker, order_id)
    assert pack is not None
    assert pack.credits_purchased == credits
    assert pack.credits_remaining == credits
    assert pack.paid_item_amount_cents == price_cents
    assert pack.currency == currency
    assert pack.provider_order_total_cents == price_cents

    status, completed_at, stamped_order_id = await _attempt_status(db_maker, attempt_id)
    assert status == "completed"
    assert completed_at is not None
    # T-296 contract: GET /billing/status 404s while provider_order_id is NULL,
    # so the grant must stamp it or a completed purchase polls as pending forever.
    assert stamped_order_id == order_id

    assert await _wh_status(db_maker, wid) == "processed"
    assert await _purchase_ledger_count(db_maker, order_id) == 1
    assert await _purchase_ledger_amount(db_maker, order_id) == credits


async def test_copies_provider_checkout_id_from_attempt(
    session, db_maker, cleanup
) -> None:
    nonce_hash = hashlib.sha256(b"nonce-chk").hexdigest()
    user = await _make_user(session, cleanup)
    attempt = await _make_attempt(
        session, user, nonce_hash, provider_checkout_id="chk_from_attempt"
    )
    order_id = f"ord_{uuid4().hex[:10]}"
    webhook = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )

    await billing_worker.handle_order_created({}, str(webhook.id))

    pack = await _pack_by_order(db_maker, order_id)
    assert pack.provider_checkout_id == "chk_from_attempt"


async def test_config_price_change_midflight_grants_attempt_snapshot(
    session, db_maker, cleanup, monkeypatch
) -> None:
    nonce_hash = hashlib.sha256(b"nonce-snap").hexdigest()
    user = await _make_user(session, cleanup)
    user_id = user.id
    # Attempt snapshot: 200 credits @ 900c.
    attempt = await _make_attempt(
        session, user, nonce_hash, credits=200, price_cents=900
    )
    # Config changes AFTER checkout creation — must not affect this purchase.
    monkeypatch.setattr(settings, "lemonsqueezy_price_cents", 1500)
    monkeypatch.setattr(settings, "lemonsqueezy_credits_per_purchase", 500)
    order_id = f"ord_{uuid4().hex[:10]}"
    # The order was charged the snapshot price (900), not the new config price.
    webhook = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )

    await billing_worker.handle_order_created({}, str(webhook.id))

    assert await _balance(db_maker, user_id) == 200  # snapshot credits, not 500
    pack = await _pack_by_order(db_maker, order_id)
    assert pack.credits_purchased == 200
    assert pack.paid_item_amount_cents == 900


# ---------------------------------------------------------------------------
# Rejections — grant nothing, but durably acknowledge (processed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"store_id": 11111}, id="wrong-store"),
        pytest.param({"variant_id": 22222}, id="wrong-variant"),
        pytest.param({"currency": "EUR"}, id="wrong-currency"),
        pytest.param({"item_price_cents": 100}, id="wrong-price"),
        pytest.param({"discount_total_cents": 50}, id="discount-present"),
        pytest.param({"test_mode": False}, id="wrong-test-mode"),
        pytest.param({"status": "pending"}, id="unpaid-pending"),
        pytest.param({"status": "failed"}, id="unpaid-failed"),
        pytest.param({"status": "refunded"}, id="status-refunded"),
        pytest.param({"status": "partial_refund"}, id="status-partial-refund"),
        pytest.param({"status": "fraudulent"}, id="status-fraudulent"),
    ],
)
async def test_rejects_invalid_order(session, db_maker, cleanup, overrides) -> None:
    nonce_hash = hashlib.sha256(b"nonce-rej").hexdigest()
    user = await _make_user(session, cleanup, balance=5)
    user_id = user.id
    attempt = await _make_attempt(session, user, nonce_hash)
    order_id = f"ord_{uuid4().hex[:10]}"
    webhook = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id, **overrides)
    )
    wid = webhook.id

    await billing_worker.handle_order_created({}, str(wid))

    assert await _balance(db_maker, user_id) == 5  # unchanged
    assert await _pack_count(db_maker, user_id) == 0
    assert await _wh_status(db_maker, wid) == "processed"  # terminal ack, not retried


async def test_forged_user_id_grants_nothing(session, db_maker, cleanup) -> None:
    nonce_hash = hashlib.sha256(b"nonce-forge").hexdigest()
    victim = await _make_user(session, cleanup, balance=0)
    attacker = await _make_user(session, cleanup, balance=0)
    victim_id, attacker_id = victim.id, attacker.id
    attempt = await _make_attempt(session, victim, nonce_hash)
    order_id = f"ord_{uuid4().hex[:10]}"
    # Attacker forges their own user_id into the custom block; nonce/ref are the
    # victim's attempt — the user_id will not match the attempt owner.
    payload = _payload(
        attempt, nonce_hash, order_id=order_id, custom={"user_id": str(attacker_id)}
    )
    webhook = await _make_webhook(session, cleanup, payload)

    await billing_worker.handle_order_created({}, str(webhook.id))

    assert await _balance(db_maker, attacker_id) == 0
    assert await _balance(db_maker, victim_id) == 0
    assert await _pack_count(db_maker, attacker_id) == 0
    assert await _pack_count(db_maker, victim_id) == 0


async def test_nonce_mismatch_grants_nothing(session, db_maker, cleanup) -> None:
    nonce_hash = hashlib.sha256(b"nonce-real").hexdigest()
    user = await _make_user(session, cleanup)
    user_id = user.id
    attempt = await _make_attempt(session, user, nonce_hash)
    order_id = f"ord_{uuid4().hex[:10]}"
    payload = _payload(
        attempt,
        nonce_hash,
        order_id=order_id,
        custom={
            "checkout_nonce_hash_from_webhook": hashlib.sha256(b"forged").hexdigest()
        },
    )
    webhook = await _make_webhook(session, cleanup, payload)

    await billing_worker.handle_order_created({}, str(webhook.id))

    assert await _balance(db_maker, user_id) == 0
    assert await _pack_count(db_maker, user_id) == 0


async def test_unknown_checkout_ref_grants_nothing(session, db_maker, cleanup) -> None:
    nonce_hash = hashlib.sha256(b"nonce-x").hexdigest()
    user = await _make_user(session, cleanup)
    user_id = user.id
    attempt = await _make_attempt(session, user, nonce_hash)
    order_id = f"ord_{uuid4().hex[:10]}"
    payload = _payload(
        attempt,
        nonce_hash,
        order_id=order_id,
        custom={"checkout_ref": "ref_does_not_exist"},
    )
    webhook = await _make_webhook(session, cleanup, payload)

    await billing_worker.handle_order_created({}, str(webhook.id))

    assert await _balance(db_maker, user_id) == 0
    assert await _pack_count(db_maker, user_id) == 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_duplicate_order_created_does_not_double_credit(
    session, db_maker, cleanup
) -> None:
    nonce_hash = hashlib.sha256(b"nonce-dup").hexdigest()
    user = await _make_user(session, cleanup)
    user_id = user.id
    attempt = await _make_attempt(session, user, nonce_hash)
    credits = attempt.credits
    order_id = f"ord_{uuid4().hex[:10]}"

    # Build BOTH inbox rows up front (the second is a provider redelivery that
    # slipped past inbox dedup — same order, different timestamps → different
    # payload_hash) before any read.
    wh1 = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )
    wh2 = await _make_webhook(
        session,
        cleanup,
        _payload(
            attempt,
            nonce_hash,
            order_id=order_id,
            updated_at="2026-06-06T11:11:11.000000Z",
        ),
    )
    wh2_id = wh2.id

    await billing_worker.handle_order_created({}, str(wh1.id))
    assert await _balance(db_maker, user_id) == credits

    await billing_worker.handle_order_created({}, str(wh2_id))

    assert await _balance(db_maker, user_id) == credits  # not doubled
    assert await _pack_count(db_maker, user_id) == 1
    assert await _wh_status(db_maker, wh2_id) == "processed"
    assert await _purchase_ledger_count(db_maker, order_id) == 1


async def test_redelivery_backfills_legacy_null_provider_order_id(
    session, db_maker, cleanup
) -> None:
    """A redelivery heals a completed attempt whose order id was never stamped.

    Attempts granted before the provider_order_id stamp existed sit at
    status='completed' with a NULL order id, so GET /billing/status 404s them
    forever. The duplicate path backfills the id from the redelivered payload.
    """
    nonce_hash = hashlib.sha256(b"nonce-legacy").hexdigest()
    user = await _make_user(session, cleanup)
    attempt = await _make_attempt(session, user, nonce_hash)
    attempt_id = attempt.id
    order_id = f"ord_{uuid4().hex[:10]}"
    wh1 = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )
    wh2 = await _make_webhook(
        session,
        cleanup,
        _payload(
            attempt,
            nonce_hash,
            order_id=order_id,
            updated_at="2026-06-06T12:12:12.000000Z",
        ),
    )
    wh2_id = wh2.id

    await billing_worker.handle_order_created({}, str(wh1.id))

    # Simulate the legacy pre-fix state: granted, but the stamp never happened.
    async with db_maker() as db:
        legacy = await db.get(BillingCheckoutAttempt, attempt_id)
        legacy.provider_order_id = None
        await db.commit()

    await billing_worker.handle_order_created({}, str(wh2_id))

    status, _, stamped_order_id = await _attempt_status(db_maker, attempt_id)
    assert status == "completed"
    assert stamped_order_id == order_id
    assert await _wh_status(db_maker, wh2_id) == "processed"


async def test_reprocessing_same_row_is_idempotent(session, db_maker, cleanup) -> None:
    nonce_hash = hashlib.sha256(b"nonce-reproc").hexdigest()
    user = await _make_user(session, cleanup)
    user_id = user.id
    attempt = await _make_attempt(session, user, nonce_hash)
    credits = attempt.credits
    order_id = f"ord_{uuid4().hex[:10]}"
    webhook = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )
    wid = webhook.id

    await billing_worker.handle_order_created({}, str(wid))
    # The sweep/reconcile can re-invoke the handler for the same row; processed
    # short-circuit means no second grant.
    await billing_worker.handle_order_created({}, str(wid))

    assert await _balance(db_maker, user_id) == credits
    assert await _pack_count(db_maker, user_id) == 1
    assert await _purchase_ledger_count(db_maker, order_id) == 1


# ---------------------------------------------------------------------------
# Concurrent double-grant races (the two redelivery branches that the sequential
# duplicate tests above CANNOT reach: those resolve at the `_find_existing_pack`
# pre-check, but a truly concurrent delivery slips past that SELECT and is caught
# later — once by the pack-flush unique index, once by the ledger-reason index).
# These guard the payment audit's "double-grant race" surface (issue #35, step 2).
# ---------------------------------------------------------------------------


async def test_concurrent_pack_flush_conflict_grants_nothing(
    session, db_maker, cleanup, monkeypatch
) -> None:
    """A racing delivery commits the pack between our pre-check and our flush.

    Simulates the TOCTOU window: ``_find_existing_pack`` ran and saw nothing, then
    the winning delivery's ``(provider, provider_order_id)`` row committed, so our
    ``db.flush()`` raises ``IntegrityError`` on the partial-unique index *before*
    the grant. The handler must roll back, ack the redelivery as processed, and
    grant nothing — no second pack, no second ledger row. (Patching
    ``_find_existing_pack``→None is the only deterministic way to open the window,
    since every unique key is also a pre-check predicate; the pre-check is NOT
    broken.)  Covers handle_order_created's pack-flush IntegrityError branch.
    """
    nonce_hash = hashlib.sha256(b"nonce-race-pack").hexdigest()
    user = await _make_user(session, cleanup)
    user_id = user.id
    attempt = await _make_attempt(session, user, nonce_hash)
    credits = attempt.credits
    order_id = f"ord_{uuid4().hex[:10]}"

    # The "winner" delivery already committed its pack + purchase ledger row.
    now = datetime.now(UTC)
    winner_pack = BillingCreditPack(
        user_id=user_id,
        provider="lemonsqueezy",
        provider_checkout_id=None,
        provider_order_id=order_id,
        credits_purchased=credits,
        credits_remaining=credits,
        price_cents=attempt.price_cents,
        currency=attempt.currency,
        paid_item_amount_cents=attempt.price_cents,
        status="active",
        purchased_at=now,
        expires_at=now + timedelta(days=attempt.validity_days),
    )
    session.add(winner_pack)
    session.add(
        CreditLedger(
            user_id=user_id,
            amount=credits,
            reason=f"billing_purchase:lemonsqueezy:{order_id}",
        )
    )
    await session.commit()

    webhook = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )
    wid = webhook.id

    # Force the pre-check to miss, reproducing the race window.
    async def _miss(*_args, **_kwargs):
        return None

    monkeypatch.setattr(billing_worker, "_find_existing_pack", _miss)

    await billing_worker.handle_order_created({}, str(wid))

    # No double grant: only the winner's pack/ledger survive, balance untouched.
    assert await _pack_count(db_maker, user_id) == 1
    assert await _purchase_ledger_count(db_maker, order_id) == 1
    assert await _balance(db_maker, user_id) == 0
    # The redelivery is durably acked so the sweep stops re-driving it.
    assert await _wh_status(db_maker, wid) == "processed"


async def test_concurrent_ledger_reason_conflict_grants_nothing(
    session, db_maker, cleanup
) -> None:
    """A racing delivery commits the purchase ledger row before our grant flushes.

    Here the pack flush succeeds (no committed pack yet) but the grant's nested
    SAVEPOINT hits the ``billing_purchase:`` ledger-reason unique index and returns
    ``None``. We seed only the ledger row (the race state where the winner's pack
    is not yet visible to our SELECT). The handler must roll back the speculative
    pack, ack the redelivery, and add nothing. Covers handle_order_created's
    ``granted is None`` branch.
    """
    nonce_hash = hashlib.sha256(b"nonce-race-ledger").hexdigest()
    user = await _make_user(session, cleanup, balance=0)
    user_id = user.id
    attempt = await _make_attempt(session, user, nonce_hash)
    credits = attempt.credits
    order_id = f"ord_{uuid4().hex[:10]}"

    # The winner's purchase ledger row is already committed (its pack row is not
    # yet visible to our pre-check — the race window).
    session.add(
        CreditLedger(
            user_id=user_id,
            amount=credits,
            reason=f"billing_purchase:lemonsqueezy:{order_id}",
        )
    )
    await session.commit()

    webhook = await _make_webhook(
        session, cleanup, _payload(attempt, nonce_hash, order_id=order_id)
    )
    wid = webhook.id

    await billing_worker.handle_order_created({}, str(wid))

    # The grant returned None: speculative pack rolled back, nothing granted.
    assert await _pack_count(db_maker, user_id) == 0
    assert await _purchase_ledger_count(db_maker, order_id) == 1
    assert await _balance(db_maker, user_id) == 0
    assert await _wh_status(db_maker, wid) == "processed"

"""Behavioural tests for `order_refunded` / fraud / debt processing (Phase 22 — T-300).

The refund path is the most intricate money math in the phase: tax-normalised
proportional revocation, a monotonic per-level idempotency barrier, deadlock-safe
single-ordered pack locking, and recoverable credit debt. The source-grep harness
cannot run any of it, so these are real-Postgres integration tests gated on
``TEST_DATABASE_URL`` (mirroring ``test_billing_order_created.py``): they skip
locally and run in CI against the migrated database (the ``refund:billing:`` and
``billing_purchase:`` ledger-reason unique indexes live in migration 0018).

``handle_order_refunded`` calls the module-level ``AsyncSessionLocal`` and the
``credit_service`` singleton directly; we point the former at a per-test NullPool
maker (loop-safety, as the worker suite does).
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
from models.billing_credit_debt import BillingCreditDebt
from models.billing_credit_pack import BillingCreditPack
from models.billing_webhook_event import BillingWebhookEvent
from services import billing_worker

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason=(
            "TEST_DATABASE_URL not set — Postgres refund integration test skipped. "
            "Runs in CI against the migrated test database. T-300."
        ),
    ),
]


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


class _Tracker:
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
        # debts reference packs via RESTRICT FK — delete debts before packs.
        await session.execute(
            delete(BillingCreditDebt).where(BillingCreditDebt.user_id == uid)
        )
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


async def _make_user(session: AsyncSession, cleanup, *, balance: int) -> User:
    u = User(
        email=f"order-refund-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Order Refund Tester",
        avatar_url=None,
        credit_balance=balance,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    cleanup.users.append(u.id)
    return u


async def _make_pack(
    session: AsyncSession,
    user: User,
    *,
    order_id: str,
    credits_purchased: int = 200,
    credits_remaining: int | None = None,
    credits_consumed: int = 0,
    credits_expired: int = 0,
    paid_item_cents: int = 900,
    order_total_cents: int | None = 900,
    currency: str = "USD",
    status: str = "active",
) -> BillingCreditPack:
    pack = BillingCreditPack(
        user_id=user.id,
        provider="lemonsqueezy",
        provider_checkout_id=f"chk_{uuid4().hex[:10]}",
        provider_order_id=order_id,
        provider_customer_id="cust_1",
        provider_variant_id="99999",
        credits_purchased=credits_purchased,
        credits_remaining=(
            credits_purchased if credits_remaining is None else credits_remaining
        ),
        credits_consumed=credits_consumed,
        credits_expired=credits_expired,
        price_cents=paid_item_cents,
        currency=currency,
        paid_item_amount_cents=paid_item_cents,
        provider_order_total_cents=order_total_cents,
        status=status,
        purchased_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=29),
    )
    session.add(pack)
    await session.commit()
    await session.refresh(pack)
    return pack


async def _make_attempt(
    session: AsyncSession,
    user: User,
    nonce_hash: str,
    *,
    expires_in_minutes: int = 30,
    status: str = "provider_created",
) -> BillingCheckoutAttempt:
    attempt = BillingCheckoutAttempt(
        checkout_ref=f"ref_{uuid4().hex}",
        user_id=user.id,
        provider="lemonsqueezy",
        provider_checkout_id=None,
        checkout_nonce_hash=nonce_hash,
        credits=200,
        price_cents=900,
        currency="USD",
        validity_days=30,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt


def _payload(
    *,
    order_id: str,
    status: str = "refunded",
    refunded_amount_cents: int = 900,
    custom: dict | None = None,
    updated_at: str = "2026-06-06T12:00:00.000000Z",
) -> dict[str, Any]:
    return {
        "provider": "lemonsqueezy",
        "event_name": "order_refunded",
        "order_id": order_id,
        "store_id": 55555,
        "customer_id": 4242,
        "variant_id": 99999,
        "status": status,
        "currency": "USD",
        "test_mode": True,
        "item_price_cents": 900,
        "order_subtotal_cents": 900,
        "order_total_cents": 900,
        "discount_total_cents": 0,
        "refunded": True,
        "refunded_amount_cents": refunded_amount_cents,
        "created_at": "2026-06-06T10:00:00.000000Z",
        "updated_at": updated_at,
        "custom": custom if custom is not None else {},
    }


async def _make_webhook(
    session: AsyncSession,
    cleanup: _Tracker,
    payload: dict[str, Any],
    *,
    received_at: datetime | None = None,
) -> BillingWebhookEvent:
    row = BillingWebhookEvent(
        provider="lemonsqueezy",
        event_name="order_refunded",
        provider_object_type="orders",
        provider_object_id=payload["order_id"],
        payload_hash=hashlib.sha256(repr(payload).encode()).hexdigest(),
        status="received",
        normalized_payload=payload,
    )
    session.add(row)
    await session.flush()
    if received_at is not None:
        row.received_at = received_at
    await session.commit()
    await session.refresh(row)
    cleanup.webhooks.append(row.id)
    return row


# Fresh-session column reads (no stale identity-map objects).


async def _balance(maker: async_sessionmaker, user_id: UUID) -> int:
    async with maker() as db:
        return await db.scalar(select(User.credit_balance).where(User.id == user_id))


async def _pack(maker: async_sessionmaker, pack_id: UUID) -> BillingCreditPack:
    async with maker() as db:
        return await db.scalar(
            select(BillingCreditPack).where(BillingCreditPack.id == pack_id)
        )


async def _wh_status(maker: async_sessionmaker, wid: UUID) -> tuple:
    async with maker() as db:
        row = await db.execute(
            select(BillingWebhookEvent.status, BillingWebhookEvent.last_error).where(
                BillingWebhookEvent.id == wid
            )
        )
        return row.one()


async def _refund_ledger(maker: async_sessionmaker, pack_id: UUID) -> list:
    async with maker() as db:
        rows = await db.execute(
            select(CreditLedger.amount, CreditLedger.reason)
            .where(CreditLedger.reason.like(f"refund:billing:{pack_id}:%"))
            .order_by(CreditLedger.created_at.asc())
        )
        return list(rows.all())


async def _debt(maker: async_sessionmaker, pack_id: UUID) -> BillingCreditDebt | None:
    async with maker() as db:
        return await db.scalar(
            select(BillingCreditDebt).where(BillingCreditDebt.source_pack_id == pack_id)
        )


def _conservation_ok(pack: BillingCreditPack) -> bool:
    return (
        pack.credits_remaining
        + pack.credits_consumed
        + pack.credits_expired
        + pack.credits_debt_recovered
        <= pack.credits_purchased
    )


# ---------------------------------------------------------------------------
# Full / partial / tax / fraud revocation
# ---------------------------------------------------------------------------


async def test_full_refund_revokes_all_remaining_once(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id
    wh = await _make_webhook(
        session, cleanup, _payload(order_id=order_id, refunded_amount_cents=900)
    )

    await billing_worker.handle_order_refunded({}, str(wh.id))

    assert await _balance(db_maker, user_id) == 0
    p = await _pack(db_maker, pack_id)
    assert p.credits_remaining == 0
    assert p.credits_revoked == 200
    assert p.status == "refunded"
    assert p.refunded_item_amount_cents_processed == 900
    ledger = await _refund_ledger(db_maker, pack_id)
    assert ledger == [(-200, f"refund:billing:{pack_id}:900")]
    assert await _debt(db_maker, pack_id) is None
    assert _conservation_ok(p)


async def test_partial_refund_uses_floor_and_unprocessed_delta(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id)  # 200cr @ 900c
    pack_id, user_id = pack.id, user.id

    # First partial: refund half the order → revoke half the credits.
    wh1 = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="partial_refund", refunded_amount_cents=450),
    )
    await billing_worker.handle_order_refunded({}, str(wh1.id))

    assert await _balance(db_maker, user_id) == 100
    p = await _pack(db_maker, pack_id)
    assert p.credits_remaining == 100
    assert p.credits_revoked == 100
    assert p.status == "active"
    assert p.refunded_item_amount_cents_processed == 450

    # Second event escalates to a FULL refund (cumulative 900) → only the
    # unprocessed delta (another 100) is revoked, not 200 again.
    wh2 = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="refunded", refunded_amount_cents=900),
    )
    await billing_worker.handle_order_refunded({}, str(wh2.id))

    assert await _balance(db_maker, user_id) == 0
    p = await _pack(db_maker, pack_id)
    assert p.credits_remaining == 0
    assert p.credits_revoked == 200
    assert p.status == "refunded"
    ledger = await _refund_ledger(db_maker, pack_id)
    assert ledger == [
        (-100, f"refund:billing:{pack_id}:450"),
        (-100, f"refund:billing:{pack_id}:900"),
    ]


async def test_tax_inclusive_refund_normalised_through_order_total(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    # paid_item 900, order total 990 (90c tax). A full refund returns 990 incl tax.
    pack = await _make_pack(session, user, order_id=order_id, order_total_cents=990)
    pack_id, user_id = pack.id, user.id
    wh = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="refunded", refunded_amount_cents=990),
    )

    await billing_worker.handle_order_refunded({}, str(wh.id))

    # Normalised through the order total → new == paid_item (900), all 200 revoked.
    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 200
    assert p.refunded_item_amount_cents_processed == 900  # item cents, not 990
    assert await _balance(db_maker, user_id) == 0


async def test_partial_tax_inclusive_does_not_over_revoke(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id, order_total_cents=990)
    pack_id, user_id = pack.id, user.id
    # Refund half the GROSS (495 of 990) → floor(900*495/990)=450 item cents →
    # floor(200*450/900)=100 credits, not 200.
    wh = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="partial_refund", refunded_amount_cents=495),
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    p = await _pack(db_maker, pack_id)
    assert p.refunded_item_amount_cents_processed == 450
    assert p.credits_revoked == 100
    assert await _balance(db_maker, user_id) == 100


async def test_fraud_with_zero_amount_revokes_all(session, db_maker, cleanup) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id
    # A chargeback flagged fraudulent can carry refunded_amount=0 — the status
    # string drives the full reversal.
    wh = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="fraudulent", refunded_amount_cents=0),
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 200
    assert p.status == "refunded"
    assert await _balance(db_maker, user_id) == 0


async def test_signed_refund_without_custom_data_revokes_by_order_id(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id
    # No custom block at all — ownership is the provider_order_id match.
    wh = await _make_webhook(session, cleanup, _payload(order_id=order_id, custom={}))
    await billing_worker.handle_order_refunded({}, str(wh.id))

    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 200
    assert await _balance(db_maker, user_id) == 0


# ---------------------------------------------------------------------------
# Idempotency / monotonic processed level
# ---------------------------------------------------------------------------


async def test_replay_same_amount_is_noop(session, db_maker, cleanup) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id

    wh1 = await _make_webhook(
        session, cleanup, _payload(order_id=order_id, refunded_amount_cents=900)
    )
    await billing_worker.handle_order_refunded({}, str(wh1.id))
    assert await _balance(db_maker, user_id) == 0

    # A redelivery with the same refund level (distinct payload_hash via a later
    # updated_at, so it is a separate inbox row) is a durable no-op.
    wh2 = await _make_webhook(
        session,
        cleanup,
        _payload(
            order_id=order_id,
            refunded_amount_cents=900,
            updated_at="2026-06-07T09:00:00.000000Z",
        ),
    )
    await billing_worker.handle_order_refunded({}, str(wh2.id))

    assert await _balance(db_maker, user_id) == 0
    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 200  # not 400
    assert len(await _refund_ledger(db_maker, pack_id)) == 1
    assert (await _wh_status(db_maker, wh2.id))[0] == "processed"


async def test_lower_replay_after_partial_is_noop(session, db_maker, cleanup) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id

    wh1 = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="partial_refund", refunded_amount_cents=450),
    )
    await billing_worker.handle_order_refunded({}, str(wh1.id))
    assert await _balance(db_maker, user_id) == 100

    # A later event reporting a LOWER cumulative refund (out-of-order delivery) is
    # a no-op — the monotonic processed level guards it.
    wh2 = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="partial_refund", refunded_amount_cents=100),
    )
    await billing_worker.handle_order_refunded({}, str(wh2.id))

    assert await _balance(db_maker, user_id) == 100
    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 100
    assert p.refunded_item_amount_cents_processed == 450  # unchanged
    assert len(await _refund_ledger(db_maker, pack_id)) == 1


async def test_zero_effective_refund_advances_processed_state(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=1)
    order_id = f"ord_{uuid4().hex[:10]}"
    # 1 credit @ 900c. A 1-cent refund → 1 item-cent → floor(1*1/900)=0 credits.
    pack = await _make_pack(
        session, user, order_id=order_id, credits_purchased=1, paid_item_cents=900
    )
    pack_id, user_id = pack.id, user.id
    wh = await _make_webhook(
        session,
        cleanup,
        _payload(order_id=order_id, status="partial_refund", refunded_amount_cents=1),
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 0
    assert p.refunded_item_amount_cents_processed == 1  # advanced
    assert p.provider_refunded_total_cents_seen == 1
    assert await _balance(db_maker, user_id) == 1  # unchanged
    assert await _refund_ledger(db_maker, pack_id) == []
    assert (await _wh_status(db_maker, wh.id))[0] == "processed"


# ---------------------------------------------------------------------------
# Debt creation / expiry
# ---------------------------------------------------------------------------


async def test_refund_after_spend_creates_debt(session, db_maker, cleanup) -> None:
    # 200cr purchased, 150 already spent → 50 remaining, balance 50.
    user = await _make_user(session, cleanup, balance=50)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(
        session,
        user,
        order_id=order_id,
        credits_purchased=200,
        credits_remaining=50,
        credits_consumed=150,
    )
    pack_id, user_id = pack.id, user.id
    wh = await _make_webhook(
        session, cleanup, _payload(order_id=order_id, refunded_amount_cents=900)
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    # All 200 revocable; 50 drained immediately (balance→0), 150 becomes debt.
    assert await _balance(db_maker, user_id) == 0
    p = await _pack(db_maker, pack_id)
    assert p.credits_remaining == 0
    assert p.credits_revoked == 200
    debt = await _debt(db_maker, pack_id)
    assert debt is not None
    assert debt.credits_owed == 150
    assert debt.status == "pending"
    ledger = await _refund_ledger(db_maker, pack_id)
    assert ledger == [(-50, f"refund:billing:{pack_id}:900")]  # only immediate drain


async def test_refund_after_expiry_creates_no_debt(session, db_maker, cleanup) -> None:
    # The pack already lapsed: 200 expired, 0 remaining, balance 0.
    user = await _make_user(session, cleanup, balance=0)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(
        session,
        user,
        order_id=order_id,
        credits_purchased=200,
        credits_remaining=0,
        credits_expired=200,
        status="expired",
    )
    pack_id, user_id = pack.id, user.id
    wh = await _make_webhook(
        session, cleanup, _payload(order_id=order_id, refunded_amount_cents=900)
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    # refundable_value = purchased - expired = 0 → nothing revoked, no debt.
    assert await _balance(db_maker, user_id) == 0
    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 0
    assert p.refunded_item_amount_cents_processed == 900  # processed still advances
    assert await _debt(db_maker, pack_id) is None
    assert await _refund_ledger(db_maker, pack_id) == []


async def test_refund_drains_other_packs_fifo_before_debt(
    session, db_maker, cleanup
) -> None:
    # Two packs; the user spent the source pack's credits but still has the other's.
    user = await _make_user(session, cleanup, balance=100)
    src_order = f"ord_{uuid4().hex[:10]}"
    other_order = f"ord_{uuid4().hex[:10]}"
    # Source: 100 purchased, fully spent (0 remaining).
    source = await _make_pack(
        session,
        user,
        order_id=src_order,
        credits_purchased=100,
        credits_remaining=0,
        credits_consumed=100,
    )
    # Other active pack, soonest-expiring drained FIFO: 100 remaining.
    other = await _make_pack(
        session,
        user,
        order_id=other_order,
        credits_purchased=100,
        credits_remaining=100,
    )
    src_id, other_id, user_id = source.id, other.id, user.id
    wh = await _make_webhook(
        session, cleanup, _payload(order_id=src_order, refunded_amount_cents=900)
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    # Revoke 100 (full of source's refundable). Source has 0 remaining → drain the
    # other pack's 100. Balance 100→0. No debt (fully recovered from the other pack).
    assert await _balance(db_maker, user_id) == 0
    o = await _pack(db_maker, other_id)
    assert o.credits_remaining == 0
    assert o.credits_debt_recovered == 100
    assert o.status == "consumed"
    s = await _pack(db_maker, src_id)
    assert s.credits_revoked == 100
    assert await _debt(db_maker, src_id) is None
    assert _conservation_ok(o)


# ---------------------------------------------------------------------------
# No-pack proof branches
# ---------------------------------------------------------------------------


async def test_missing_pack_with_proof_requeues_for_retry(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=0)
    nonce_hash = hashlib.sha256(b"nonce-retry").hexdigest()
    attempt = await _make_attempt(session, user, nonce_hash, expires_in_minutes=30)
    order_id = f"ord_{uuid4().hex[:10]}"  # no pack for this order yet
    wh = await _make_webhook(
        session,
        cleanup,
        _payload(
            order_id=order_id,
            custom={
                "user_id": str(user.id),
                "checkout_ref": attempt.checkout_ref,
                "checkout_nonce_hash_from_webhook": nonce_hash,
            },
        ),
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    # Re-queued (off the dead-letter budget) so a delayed order_created runs first.
    status, last_error = await _wh_status(db_maker, wh.id)
    assert status == "received"
    assert last_error == "pack_not_yet_granted"
    assert await _balance(db_maker, user.id) == 0


async def test_missing_pack_with_proof_gives_up_after_expiry_and_24h(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=0)
    nonce_hash = hashlib.sha256(b"nonce-giveup").hexdigest()
    # Attempt already expired (negative TTL).
    attempt = await _make_attempt(
        session, user, nonce_hash, expires_in_minutes=-120, status="expired"
    )
    order_id = f"ord_{uuid4().hex[:10]}"
    wh = await _make_webhook(
        session,
        cleanup,
        _payload(
            order_id=order_id,
            custom={
                "user_id": str(user.id),
                "checkout_ref": attempt.checkout_ref,
                "checkout_nonce_hash_from_webhook": nonce_hash,
            },
        ),
        received_at=datetime.now(UTC) - timedelta(hours=25),
    )
    await billing_worker.handle_order_refunded({}, str(wh.id))

    status, last_error = await _wh_status(db_maker, wh.id)
    assert status == "processed"
    assert last_error == "refund_pack_never_granted_attempt_expired"
    assert await _balance(db_maker, user.id) == 0


async def test_missing_pack_without_proof_audited_no_unrelated_revoke(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    # A bystander pack for a DIFFERENT order must never be touched.
    bystander_order = f"ord_{uuid4().hex[:10]}"
    bystander = await _make_pack(session, user, order_id=bystander_order)
    bystander_id, user_id = bystander.id, user.id

    order_id = f"ord_{uuid4().hex[:10]}"  # no pack, no proof
    wh = await _make_webhook(session, cleanup, _payload(order_id=order_id, custom={}))
    await billing_worker.handle_order_refunded({}, str(wh.id))

    status, last_error = await _wh_status(db_maker, wh.id)
    assert status == "processed"
    assert last_error == "refund_could_not_link_to_specforge"
    assert await _balance(db_maker, user_id) == 200  # untouched
    b = await _pack(db_maker, bystander_id)
    assert b.credits_revoked == 0
    assert b.credits_remaining == 200


async def test_reprocessing_same_refund_row_is_idempotent(
    session, db_maker, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"ord_{uuid4().hex[:10]}"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id
    wh = await _make_webhook(
        session, cleanup, _payload(order_id=order_id, refunded_amount_cents=900)
    )

    await billing_worker.handle_order_refunded({}, str(wh.id))
    # The sweep/reconcile can re-invoke the handler for the same row; the processed
    # short-circuit means no second revocation.
    await billing_worker.handle_order_refunded({}, str(wh.id))

    assert await _balance(db_maker, user_id) == 0
    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 200
    assert len(await _refund_ledger(db_maker, pack_id)) == 1

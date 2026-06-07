"""Integration tests for the late-Stripe webhook grace path (Phase 22 — T-303).

New checkout is Lemon-only (T-296); this bounded window keeps an already-created
Stripe session settling through the SAME neutral inbox + worker helpers. The
deliverables are: the grace gate (closed → ``ignored_provider_disabled`` with no DB
write / no signature claim), Stripe-signature verification, and the two worker
handlers that grant/revoke via the neutral path with backfill-aligned idempotency
keys (provider_checkout_id = session id, provider_order_id = payment_intent). These
need a real DB (the ingress uses a SAVEPOINT; the worker mutates money), so the suite
is gated on ``TEST_DATABASE_URL``. The HTTP ingress is driven through the real ASGI
app; the worker handlers are called directly (as the other worker suites do).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from database import get_db
from main import create_app
from models import CreditLedger, User
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
            "TEST_DATABASE_URL not set — Postgres Stripe-grace test skipped. "
            "Runs in CI against the migrated test database. T-303."
        ),
    ),
]

_WEBHOOK_SECRET = "whsec_test_t303"


# ---------------------------------------------------------------------------
# Fixtures / helpers
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
        self.event_ids: list[str] = []


@pytest.fixture
async def cleanup(session: AsyncSession):
    tracker = _Tracker()
    yield tracker
    if tracker.event_ids:
        await session.execute(
            delete(BillingWebhookEvent).where(
                BillingWebhookEvent.provider_object_id.in_(tracker.event_ids)
            )
        )
    for uid in tracker.users:
        await session.execute(
            delete(BillingCreditDebt).where(BillingCreditDebt.user_id == uid)
        )
        await session.execute(
            delete(BillingCreditPack).where(BillingCreditPack.user_id == uid)
        )
        await session.execute(delete(CreditLedger).where(CreditLedger.user_id == uid))
        await session.execute(delete(User).where(User.id == uid))
    await session.commit()


class _NoopRedis:
    """Redis stub that allows every rate-limit check (webhook tier is per-IP)."""

    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1


def _stripe_signature(
    body: bytes, *, secret: str = _WEBHOOK_SECRET, ts: int | None = None
) -> str:
    ts = ts or int(time.time())
    signed = f"{ts}".encode() + b"." + body
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def _checkout_event(
    *, event_id: str, session_id: str, payment_intent: str, user_id: UUID
) -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": session_id,
                "payment_intent": payment_intent,
                "payment_status": "paid",
                "amount_total": 900,
                "currency": "usd",
                "metadata": {"user_id": str(user_id)},
            }
        },
    }


def _dispute_event(*, event_id: str, payment_intent: str) -> dict:
    return {
        "id": event_id,
        "type": "charge.dispute.created",
        "created": int(time.time()),
        "data": {"object": {"payment_intent": payment_intent}},
    }


async def _make_user(session, cleanup, *, balance: int = 0) -> User:
    u = User(
        email=f"stripe-grace-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Stripe Grace Tester",
        avatar_url=None,
        credit_balance=balance,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    cleanup.users.append(u.id)
    return u


async def _make_stripe_pack(
    session, user: User, *, session_id: str, payment_intent: str, credits: int = 200
) -> BillingCreditPack:
    pack = BillingCreditPack(
        user_id=user.id,
        provider="stripe",
        provider_checkout_id=session_id,
        provider_order_id=payment_intent,
        credits_purchased=credits,
        credits_remaining=credits,
        price_cents=900,
        currency="USD",
        paid_item_amount_cents=900,
        provider_order_total_cents=900,
        status="active",
        purchased_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=29),
    )
    session.add(pack)
    await session.commit()
    await session.refresh(pack)
    return pack


async def _insert_inbox(
    session, cleanup, *, event_id: str, event_name: str, payload: dict
) -> BillingWebhookEvent:
    row = BillingWebhookEvent(
        provider="stripe",
        event_name=event_name,
        provider_object_type="event",
        provider_object_id=event_id,
        payload_hash=uuid4().hex,
        status="received",
        normalized_payload=payload,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    cleanup.event_ids.append(event_id)
    return row


def _app_with_db(db_maker):
    app = create_app(redis_client=_NoopRedis())

    async def _fake_db():
        async with db_maker() as s:
            yield s

    app.dependency_overrides[get_db] = _fake_db
    return app


async def _balance(maker, user_id: UUID) -> int:
    async with maker() as db:
        return await db.scalar(select(User.credit_balance).where(User.id == user_id))


async def _packs(maker, user_id: UUID) -> list[BillingCreditPack]:
    async with maker() as db:
        rows = await db.execute(
            select(BillingCreditPack).where(BillingCreditPack.user_id == user_id)
        )
        return list(rows.scalars().all())


async def _inbox_count(maker, event_id: str) -> int:
    async with maker() as db:
        rows = await db.execute(
            select(BillingWebhookEvent.id).where(
                BillingWebhookEvent.provider_object_id == event_id
            )
        )
        return len(rows.scalars().all())


async def _ledger(maker, reason: str) -> list:
    async with maker() as db:
        rows = await db.execute(
            select(CreditLedger.amount).where(CreditLedger.reason == reason)
        )
        return list(rows.scalars().all())


# ---------------------------------------------------------------------------
# Ingress — grace gate + signature (HTTP)
# ---------------------------------------------------------------------------


async def test_post_grace_rejects_before_any_db_write(db_maker, monkeypatch) -> None:
    # No webhook secret → grace closed. A Stripe-shaped request is rejected with
    # ignored_provider_disabled, with no DB write and no signature claim.
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    event_id = f"evt_{uuid4().hex}"
    body = json.dumps(_dispute_event(event_id=event_id, payment_intent="pi_x")).encode()
    app = _app_with_db(db_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/billing/webhook",
            content=body,
            headers={"Stripe-Signature": "t=1,v1=deadbeef"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored_provider_disabled"}
    assert await _inbox_count(db_maker, event_id) == 0  # nothing written


async def test_grace_open_rejects_bad_signature(db_maker, cleanup, monkeypatch) -> None:
    monkeypatch.setattr(settings, "stripe_webhook_secret", _WEBHOOK_SECRET)
    event_id = f"evt_{uuid4().hex}"
    cleanup.event_ids.append(event_id)
    body = json.dumps(_dispute_event(event_id=event_id, payment_intent="pi_x")).encode()
    app = _app_with_db(db_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/billing/webhook",
            content=body,
            headers={"Stripe-Signature": "t=1,v1=not_the_right_hmac"},
        )
    assert resp.status_code == 400
    assert await _inbox_count(db_maker, event_id) == 0  # nothing written


async def test_grace_open_valid_signature_enqueues_inbox_row(
    db_maker, session, cleanup, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "stripe_webhook_secret", _WEBHOOK_SECRET)
    user = await _make_user(session, cleanup)
    event_id = f"evt_{uuid4().hex}"
    cleanup.event_ids.append(event_id)
    event = _checkout_event(
        event_id=event_id,
        session_id=f"cs_{uuid4().hex}",
        payment_intent=f"pi_{uuid4().hex}",
        user_id=user.id,
    )
    body = json.dumps(event).encode()
    app = _app_with_db(db_maker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/billing/webhook",
            content=body,
            headers={"Stripe-Signature": _stripe_signature(body)},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # The sanitised inbox row is persisted (provider='stripe'); the worker grants.
    async with db_maker() as db:
        row = await db.scalar(
            select(BillingWebhookEvent).where(
                BillingWebhookEvent.provider_object_id == event_id
            )
        )
    assert row is not None
    assert row.provider == "stripe"
    assert row.event_name == "checkout.session.completed"
    assert row.normalized_payload["user_id"] == str(user.id)


# ---------------------------------------------------------------------------
# Worker handlers — grant / dispute via the neutral helpers
# ---------------------------------------------------------------------------


async def test_handler_grants_with_backfill_aligned_keys(
    db_maker, session, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=0)
    user_id = user.id
    session_id = f"cs_{uuid4().hex}"
    payment_intent = f"pi_{uuid4().hex}"
    event_id = f"evt_{uuid4().hex}"
    row = await _insert_inbox(
        session,
        cleanup,
        event_id=event_id,
        event_name="checkout.session.completed",
        payload={
            "provider": "stripe",
            "event_name": "checkout.session.completed",
            "event_id": event_id,
            "session_id": session_id,
            "payment_intent_id": payment_intent,
            "user_id": str(user_id),
            "amount_total_cents": 900,
            "currency": "USD",
            "created": int(time.time()),
        },
    )

    await billing_worker.handle_stripe_checkout_completed({}, str(row.id))

    assert await _balance(db_maker, user_id) == settings.stripe_credits_per_purchase
    packs = await _packs(db_maker, user_id)
    assert len(packs) == 1
    p = packs[0]
    assert p.provider == "stripe"
    # Keys match migration 0018's backfill exactly.
    assert p.provider_checkout_id == session_id
    assert p.provider_order_id == payment_intent
    assert await _ledger(db_maker, f"billing_purchase:stripe:{session_id}") == [
        settings.stripe_credits_per_purchase
    ]


async def test_handler_redelivery_does_not_double_credit(
    db_maker, session, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    user_id = user.id
    session_id = f"cs_{uuid4().hex}"
    payment_intent = f"pi_{uuid4().hex}"
    # A pack already settled this order (e.g. migration backfill, keyed identically).
    await _make_stripe_pack(
        session, user, session_id=session_id, payment_intent=payment_intent
    )
    event_id = f"evt_{uuid4().hex}"
    row = await _insert_inbox(
        session,
        cleanup,
        event_id=event_id,
        event_name="checkout.session.completed",
        payload={
            "session_id": session_id,
            "payment_intent_id": payment_intent,
            "user_id": str(user_id),
            "amount_total_cents": 900,
            "currency": "USD",
            "created": int(time.time()),
        },
    )

    await billing_worker.handle_stripe_checkout_completed({}, str(row.id))

    # Idempotent: the existing pack is found by the aligned keys → no second grant.
    assert await _balance(db_maker, user_id) == 200
    assert len(await _packs(db_maker, user_id)) == 1
    assert await _ledger(db_maker, f"billing_purchase:stripe:{session_id}") == []
    async with db_maker() as db:
        reloaded = await db.scalar(
            select(BillingWebhookEvent).where(BillingWebhookEvent.id == row.id)
        )
        assert reloaded.status == "processed"


async def test_dispute_revokes_via_neutral_helper(db_maker, session, cleanup) -> None:
    user = await _make_user(session, cleanup, balance=200)
    user_id = user.id
    session_id = f"cs_{uuid4().hex}"
    payment_intent = f"pi_{uuid4().hex}"
    pack = await _make_stripe_pack(
        session, user, session_id=session_id, payment_intent=payment_intent
    )
    pack_id = pack.id
    event_id = f"evt_{uuid4().hex}"
    row = await _insert_inbox(
        session,
        cleanup,
        event_id=event_id,
        event_name="charge.dispute.created",
        payload={
            "provider": "stripe",
            "event_name": "charge.dispute.created",
            "event_id": event_id,
            "payment_intent_id": payment_intent,
            "created": int(time.time()),
        },
    )

    await billing_worker.handle_stripe_dispute_created({}, str(row.id))

    # Full reversal via the same T-300 helper, found by payment_intent.
    assert await _balance(db_maker, user_id) == 0
    async with db_maker() as db:
        p = await db.scalar(
            select(BillingCreditPack).where(BillingCreditPack.id == pack_id)
        )
        assert p.credits_revoked == 200
        assert p.status == "refunded"


async def test_dispute_without_matching_pack_is_audited_noop(
    db_maker, session, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    user_id = user.id
    # A bystander stripe pack for a DIFFERENT payment intent must be untouched.
    await _make_stripe_pack(
        session,
        user,
        session_id=f"cs_{uuid4().hex}",
        payment_intent=f"pi_other_{uuid4().hex}",
    )
    event_id = f"evt_{uuid4().hex}"
    row = await _insert_inbox(
        session,
        cleanup,
        event_id=event_id,
        event_name="charge.dispute.created",
        payload={
            "payment_intent_id": f"pi_unknown_{uuid4().hex}",
            "created": int(time.time()),
        },
    )

    await billing_worker.handle_stripe_dispute_created({}, str(row.id))

    assert await _balance(db_maker, user_id) == 200  # untouched
    async with db_maker() as db:
        reloaded = await db.scalar(
            select(BillingWebhookEvent).where(BillingWebhookEvent.id == row.id)
        )
        assert reloaded.status == "processed"
        assert reloaded.last_error == "stripe_grace_dispute_could_not_link"


async def test_handler_reprocessing_same_row_is_idempotent(
    db_maker, session, cleanup
) -> None:
    user = await _make_user(session, cleanup, balance=0)
    user_id = user.id
    session_id = f"cs_{uuid4().hex}"
    payment_intent = f"pi_{uuid4().hex}"
    event_id = f"evt_{uuid4().hex}"
    row = await _insert_inbox(
        session,
        cleanup,
        event_id=event_id,
        event_name="checkout.session.completed",
        payload={
            "session_id": session_id,
            "payment_intent_id": payment_intent,
            "user_id": str(user_id),
            "amount_total_cents": 900,
            "currency": "USD",
            "created": int(time.time()),
        },
    )

    await billing_worker.handle_stripe_checkout_completed({}, str(row.id))
    await billing_worker.handle_stripe_checkout_completed({}, str(row.id))

    assert await _balance(db_maker, user_id) == settings.stripe_credits_per_purchase
    assert len(await _packs(db_maker, user_id)) == 1

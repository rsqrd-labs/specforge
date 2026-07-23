"""Integration tests for the admin billing-correction support path (Phase 22 — T-302).

The endpoint is the exceptional, allowlist-gated manual grant for a provably-paid
order the webhook pipeline could not settle. Its deliverable is authorization +
money correctness: ``require_admin`` (closed by default), an atomic pack + ledger +
immutable audit write, debt-first recovery, and idempotency on
``(provider, provider_order_id)``. The money/atomicity behaviours need a real DB, so
these are real-Postgres tests gated on ``TEST_DATABASE_URL`` (mirroring the other
billing suites). The endpoint function and ``require_admin`` are called directly —
CSRF/rate-limit are middleware tested elsewhere; authz here is ``require_admin``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import (
    BillingAdminCorrection,
    BillingCreditDebt,
    BillingCreditPack,
    CreditLedger,
    User,
)
from models.billing_checkout_attempt import BillingCheckoutAttempt
from models.billing_webhook_event import BillingWebhookEvent
from routers.billing import admin_correction, require_admin
from schemas.billing import AdminCorrectionRequest
from services import billing_worker

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason=(
            "TEST_DATABASE_URL not set — Postgres admin-correction test skipped. "
            "Runs in CI against the migrated test database. T-302."
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
    # The endpoint resolves its own session via Depends(get_db) in production; the
    # billing worker (used by the late-webhook test) calls AsyncSessionLocal directly.
    monkeypatch.setattr(billing_worker, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()


@pytest.fixture
async def session(db_maker: async_sessionmaker) -> AsyncSession:
    async with db_maker() as db:
        yield db


@pytest.fixture(autouse=True)
def admin_allowlist(monkeypatch):
    """Default: a single allowlisted admin email. Tests override as needed."""
    monkeypatch.setattr(settings, "admin_user_emails", "admin@thought2build.com")
    yield


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
        # corrections + debts reference packs/users via RESTRICT — delete first.
        await session.execute(
            delete(BillingAdminCorrection).where(
                BillingAdminCorrection.target_user_id == uid
            )
        )
        await session.execute(
            delete(BillingAdminCorrection).where(
                BillingAdminCorrection.admin_user_id == uid
            )
        )
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


async def _make_user(session, cleanup, *, email: str, balance: int = 0) -> User:
    u = User(
        email=email,
        google_id=f"google-{uuid4()}",
        name="Admin Correction Tester",
        avatar_url=None,
        credit_balance=balance,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    cleanup.users.append(u.id)
    return u


def _request(
    target_id: UUID, *, order_id: str, credits: int = 200
) -> AdminCorrectionRequest:
    return AdminCorrectionRequest(
        provider="lemonsqueezy",
        provider_order_id=order_id,
        target_user_id=target_id,
        credits=credits,
        price_cents=900,
        currency="USD",
        reason="paid order, webhook never arrived (ticket #123)",
        evidence_url="https://support.thought2build.com/tickets/123",
    )


async def _seed_debt(session, user_id: UUID, *, owed: int) -> BillingCreditDebt:
    source = BillingCreditPack(
        user_id=user_id,
        provider="lemonsqueezy",
        provider_order_id=f"ord_src_{uuid4().hex[:10]}",
        credits_purchased=owed,
        credits_remaining=0,
        credits_revoked=owed,
        price_cents=900,
        currency="USD",
        paid_item_amount_cents=900,
        status="refunded",
        purchased_at=datetime.now(UTC) - timedelta(days=2),
        expires_at=datetime.now(UTC) + timedelta(days=28),
    )
    session.add(source)
    await session.flush()
    debt = BillingCreditDebt(
        user_id=user_id,
        source_pack_id=source.id,
        provider="lemonsqueezy",
        provider_order_id=source.provider_order_id,
        credits_owed=owed,
        credits_recovered=0,
        status="pending",
        reason="refund_exceeded_remaining",
    )
    session.add(debt)
    await session.commit()
    return debt


# Fresh-session reads.


async def _balance(maker, user_id: UUID) -> int:
    async with maker() as db:
        return await db.scalar(select(User.credit_balance).where(User.id == user_id))


async def _packs(maker, user_id: UUID) -> list[BillingCreditPack]:
    async with maker() as db:
        rows = await db.execute(
            select(BillingCreditPack).where(BillingCreditPack.user_id == user_id)
        )
        return list(rows.scalars().all())


async def _corrections(maker, order_id: str) -> list[BillingAdminCorrection]:
    async with maker() as db:
        rows = await db.execute(
            select(BillingAdminCorrection).where(
                BillingAdminCorrection.provider_order_id == order_id
            )
        )
        return list(rows.scalars().all())


async def _ledger(maker, reason: str) -> list:
    async with maker() as db:
        rows = await db.execute(
            select(CreditLedger.amount).where(CreditLedger.reason == reason)
        )
        return list(rows.scalars().all())


# ---------------------------------------------------------------------------
# require_admin — authorization (allow / deny / empty allowlist)
# ---------------------------------------------------------------------------


async def test_require_admin_allows_allowlisted(session, cleanup) -> None:
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    result = await require_admin(current_user=admin)
    assert result is admin


async def test_require_admin_denies_non_allowlisted(session, cleanup) -> None:
    user = await _make_user(session, cleanup, email="someone@example.com")
    with pytest.raises(HTTPException) as exc:
        await require_admin(current_user=user)
    assert exc.value.status_code == 403


async def test_require_admin_empty_allowlist_denies_everyone(
    session, cleanup, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "admin_user_emails", "")
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    with pytest.raises(HTTPException) as exc:
        await require_admin(current_user=admin)
    assert exc.value.status_code == 403  # no implicit admin


async def test_require_admin_is_case_insensitive(session, cleanup) -> None:
    user = await _make_user(session, cleanup, email="Admin@thought2build.com")
    assert await require_admin(current_user=user) is user


# ---------------------------------------------------------------------------
# Correction — atomic pack + ledger + audit, debt-first, idempotent
# ---------------------------------------------------------------------------


async def test_correction_creates_pack_ledger_and_audit_atomically(
    session, db_maker, cleanup
) -> None:
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    target = await _make_user(session, cleanup, email="payer@example.com", balance=0)
    order_id = f"ord_{uuid4().hex[:10]}"

    async with db_maker() as db:
        resp = await admin_correction(_request(target.id, order_id=order_id), admin, db)

    assert resp.applied is True
    assert resp.credits_granted == 200
    assert await _balance(db_maker, target.id) == 200

    packs = await _packs(db_maker, target.id)
    assert len(packs) == 1
    assert packs[0].provider_order_id == order_id
    assert packs[0].credits_purchased == 200
    assert packs[0].status == "active"

    assert await _ledger(
        db_maker, f"admin_billing_correction:lemonsqueezy:{order_id}"
    ) == [200]

    corrections = await _corrections(db_maker, order_id)
    assert len(corrections) == 1
    c = corrections[0]
    assert c.admin_user_id == admin.id
    assert c.target_user_id == target.id
    assert c.billing_credit_pack_id == packs[0].id
    assert c.credits == 200
    assert c.evidence_url == "https://support.thought2build.com/tickets/123"


async def test_correction_applies_debt_recovery_before_usable_credit(
    session, db_maker, cleanup
) -> None:
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    target = await _make_user(session, cleanup, email="indebted@example.com", balance=0)
    await _seed_debt(session, target.id, owed=50)
    order_id = f"ord_{uuid4().hex[:10]}"

    async with db_maker() as db:
        resp = await admin_correction(
            _request(target.id, order_id=order_id, credits=200), admin, db
        )

    assert resp.applied is True
    # 50 of the 200 corrected credits repay the debt first → 150 usable.
    assert await _balance(db_maker, target.id) == 150
    async with db_maker() as db:
        debt = await db.scalar(
            select(BillingCreditDebt).where(BillingCreditDebt.user_id == target.id)
        )
        assert debt.status == "recovered"
        assert debt.credits_recovered == 50
        pack = await db.scalar(
            select(BillingCreditPack).where(
                BillingCreditPack.provider_order_id == order_id
            )
        )
        assert pack.credits_debt_recovered == 50
        assert pack.credits_remaining == 150


async def test_duplicate_correction_is_noop(session, db_maker, cleanup) -> None:
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    target = await _make_user(session, cleanup, email="dup@example.com", balance=0)
    order_id = f"ord_{uuid4().hex[:10]}"

    async with db_maker() as db:
        first = await admin_correction(
            _request(target.id, order_id=order_id), admin, db
        )
    async with db_maker() as db:
        second = await admin_correction(
            _request(target.id, order_id=order_id), admin, db
        )

    assert first.applied is True
    assert second.applied is False
    assert second.credits_granted == 0
    # No double grant: one pack, one ledger row, one audit row, balance unchanged.
    assert await _balance(db_maker, target.id) == 200
    assert len(await _packs(db_maker, target.id)) == 1
    assert len(await _corrections(db_maker, order_id)) == 1
    assert await _ledger(
        db_maker, f"admin_billing_correction:lemonsqueezy:{order_id}"
    ) == [200]


async def test_correction_noop_when_pack_already_exists(
    session, db_maker, cleanup
) -> None:
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    target = await _make_user(
        session, cleanup, email="haspack@example.com", balance=200
    )
    order_id = f"ord_{uuid4().hex[:10]}"
    # A pack already settled this order (e.g. the webhook eventually landed).
    existing = BillingCreditPack(
        user_id=target.id,
        provider="lemonsqueezy",
        provider_order_id=order_id,
        credits_purchased=200,
        credits_remaining=200,
        price_cents=900,
        currency="USD",
        paid_item_amount_cents=900,
        status="active",
        purchased_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(existing)
    await session.commit()

    async with db_maker() as db:
        resp = await admin_correction(_request(target.id, order_id=order_id), admin, db)

    assert resp.applied is False
    assert await _balance(db_maker, target.id) == 200  # unchanged
    assert len(await _packs(db_maker, target.id)) == 1  # no second pack
    assert await _corrections(db_maker, order_id) == []  # no audit row written


async def test_correction_target_user_not_found(session, db_maker, cleanup) -> None:
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    order_id = f"ord_{uuid4().hex[:10]}"
    async with db_maker() as db:
        with pytest.raises(HTTPException) as exc:
            await admin_correction(_request(uuid4(), order_id=order_id), admin, db)
    assert exc.value.status_code == 404


async def test_ledger_collision_rolls_back_atomically(
    session, db_maker, cleanup
) -> None:
    # Pre-seed ONLY a ledger row with the correction's reason (no pack, no audit) so
    # the pre-check passes but grant() collides on the admin_billing_correction:%
    # index and returns None. Nothing of ours must commit (the flushed pack included).
    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    target = await _make_user(session, cleanup, email="collide@example.com", balance=0)
    order_id = f"ord_{uuid4().hex[:10]}"
    reason = f"admin_billing_correction:lemonsqueezy:{order_id}"
    session.add(CreditLedger(user_id=target.id, amount=0, reason=reason))
    await session.commit()

    async with db_maker() as db:
        resp = await admin_correction(_request(target.id, order_id=order_id), admin, db)

    assert resp.applied is False
    assert await _balance(db_maker, target.id) == 0  # no grant
    assert await _packs(db_maker, target.id) == []  # the flushed pack rolled back
    assert await _corrections(db_maker, order_id) == []  # no audit row
    assert await _ledger(db_maker, reason) == [0]  # only the pre-seeded row


# ---------------------------------------------------------------------------
# Cross-task: a late order_created for a corrected order must not double-grant
# ---------------------------------------------------------------------------


async def test_late_webhook_after_correction_does_not_double_grant(
    session, db_maker, cleanup, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "lemonsqueezy_store_id", "55555")
    monkeypatch.setattr(settings, "lemonsqueezy_variant_id", "99999")
    monkeypatch.setattr(settings, "lemonsqueezy_test_mode", True)

    admin = await _make_user(session, cleanup, email="admin@thought2build.com")
    target = await _make_user(session, cleanup, email="late@example.com", balance=0)
    order_id = f"ord_{uuid4().hex[:10]}"

    # 1. Admin correction settles the order (creates a pack with provider_order_id).
    async with db_maker() as db:
        await admin_correction(_request(target.id, order_id=order_id), admin, db)
    assert await _balance(db_maker, target.id) == 200

    # 2. The original signed order_created webhook finally arrives for the SAME order.
    nonce_hash = "n" * 64
    attempt = BillingCheckoutAttempt(
        checkout_ref=f"ref_{uuid4().hex}",
        user_id=target.id,
        provider="lemonsqueezy",
        provider_checkout_id="chk_late",
        checkout_nonce_hash=nonce_hash,
        credits=200,
        price_cents=900,
        currency="USD",
        validity_days=30,
        status="provider_created",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)

    webhook = BillingWebhookEvent(
        provider="lemonsqueezy",
        event_name="order_created",
        provider_object_type="orders",
        provider_object_id=order_id,
        payload_hash=uuid4().hex,
        status="received",
        normalized_payload={
            "provider": "lemonsqueezy",
            "event_name": "order_created",
            "order_id": order_id,
            "store_id": 55555,
            "variant_id": 99999,
            "status": "paid",
            "currency": "USD",
            "test_mode": True,
            "item_price_cents": 900,
            "order_total_cents": 900,
            "discount_total_cents": 0,
            "created_at": "2026-06-07T10:00:00.000000Z",
            "custom": {
                "user_id": str(target.id),
                "checkout_ref": attempt.checkout_ref,
                "checkout_nonce_hash_from_webhook": nonce_hash,
            },
        },
    )
    session.add(webhook)
    await session.commit()
    await session.refresh(webhook)
    cleanup.webhooks.append(webhook.id)

    await billing_worker.handle_order_created({}, str(webhook.id))

    # The pack for this order already exists (from the correction) → idempotent
    # no-op, NOT a second grant. Balance stays at the corrected 200.
    assert await _balance(db_maker, target.id) == 200
    assert len(await _packs(db_maker, target.id)) == 1
    async with db_maker() as db:
        wh = await db.scalar(
            select(BillingWebhookEvent).where(BillingWebhookEvent.id == webhook.id)
        )
        assert wh.status == "processed"

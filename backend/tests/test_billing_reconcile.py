"""Integration tests for the 15-minute reconciliation cron (Phase 22 — T-301).

`billing_reconcile`'s deliverable is concurrency + provider-I/O semantics — a
`FOR UPDATE NOWAIT` single-run lock, cursor-paged bounded lane-2 order re-reads,
the never-auto-grant invariant, and advance-cursor-only-on-success. None of that
can be exercised by the source-grep harness, so these are real-Postgres tests
gated on ``TEST_DATABASE_URL`` (mirroring the other billing worker suites). The
Lemon API is faked (only the HTTP boundary is replaced; the DB logic is real).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import CreditLedger, User
from models.billing_checkout_attempt import BillingCheckoutAttempt
from models.billing_credit_debt import BillingCreditDebt
from models.billing_credit_pack import BillingCreditPack
from models.billing_reconciliation_cursor import BillingReconciliationCursor
from models.billing_webhook_event import BillingWebhookEvent
from services import billing_worker
from services.lemonsqueezy_service import (
    LemonOrder,
    LemonSqueezyError,
    LemonSqueezyRateLimitError,
)
from services.observability import BILLING_CHECKOUT_EXPIRED
from services.razorpay_service import (
    RazorpayPayment,
    RazorpayRateLimitError,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason=(
            "TEST_DATABASE_URL not set — Postgres reconcile integration test skipped. "
            "Runs in CI against the migrated test database. T-301."
        ),
    ),
]

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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


async def _reset_all_cursors(session: AsyncSession) -> None:
    # Both the lemonsqueezy row (0018) and the razorpay row (0034) are now claimed
    # and advanced by every reconcile run, so reset both to a clean baseline.
    await session.execute(
        update(BillingReconciliationCursor).values(
            last_successful_run_at=_EPOCH,
            last_run_started_at=None,
            last_run_completed_at=None,
            last_error=None,
            state={},
        )
    )
    await session.commit()


@pytest.fixture(autouse=True)
async def reset_cursor(session: AsyncSession):
    """Reset every reconcile cursor to a clean baseline around each test."""
    await _reset_all_cursors(session)
    yield
    await _reset_all_cursors(session)


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


class _FakeLemon:
    """Fake LemonSqueezyService.get_order — records calls, returns/raises per order.

    Unknown order ids default to a still-``paid`` order (no reversal), so foreign
    packs that happen to be in the scan window cause no mutation.
    """

    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}
        self.calls: list[str] = []

    def set(self, order_id: str, value: Any) -> None:
        self.responses[order_id] = value

    async def get_order(self, provider_order_id: str, *, client: Any = None):
        self.calls.append(provider_order_id)
        value = self.responses.get(provider_order_id)
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return value
        return LemonOrder(
            provider_order_id=provider_order_id,
            status="paid",
            refunded=False,
            refunded_amount_cents=0,
            total_cents=900,
        )


@pytest.fixture
def fake_lemon(monkeypatch) -> _FakeLemon:
    fake = _FakeLemon()
    monkeypatch.setattr(billing_worker, "lemonsqueezy_service", fake)
    yield fake


class _FakeRazorpay:
    """Fake RazorpayService.get_payment — records calls, returns/raises per id.

    Unknown payment ids default to a ``captured`` payment with no refund, so a
    foreign pack that happens to be in the scan window causes no mutation.
    """

    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}
        self.calls: list[str] = []

    def set(self, payment_id: str, value: Any) -> None:
        self.responses[payment_id] = value

    async def get_payment(self, payment_id: str, *, client: Any = None):
        self.calls.append(payment_id)
        value = self.responses.get(payment_id)
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return value
        return RazorpayPayment(
            payment_id=payment_id,
            status="captured",
            amount_cents=79900,
            amount_refunded_cents=0,
            refund_status="",
        )


@pytest.fixture
def fake_razorpay(monkeypatch) -> _FakeRazorpay:
    fake = _FakeRazorpay()
    monkeypatch.setattr(billing_worker, "razorpay_service", fake)
    yield fake


class _RecordingPool:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def enqueue_job(self, *args: Any, **kwargs: Any):
        self.calls.append((args, kwargs))

        class _Job:
            job_id = kwargs.get("_job_id")

        return _Job()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


async def _make_user(session, cleanup, *, balance: int) -> User:
    u = User(
        email=f"reconcile-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Reconcile Tester",
        avatar_url=None,
        credit_balance=balance,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    cleanup.users.append(u.id)
    return u


async def _make_pack(
    session,
    user: User,
    *,
    order_id: str,
    credits: int = 200,
    paid_item_cents: int = 900,
    order_total_cents: int = 900,
    status: str = "active",
) -> BillingCreditPack:
    pack = BillingCreditPack(
        user_id=user.id,
        provider="lemonsqueezy",
        provider_checkout_id=f"chk_{uuid4().hex[:10]}",
        provider_order_id=order_id,
        credits_purchased=credits,
        credits_remaining=credits,
        price_cents=paid_item_cents,
        currency="USD",
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
    session, user: User, *, status: str, expires_in_minutes: int
) -> BillingCheckoutAttempt:
    attempt = BillingCheckoutAttempt(
        checkout_ref=f"ref_{uuid4().hex}",
        user_id=user.id,
        provider="lemonsqueezy",
        checkout_nonce_hash="x" * 64,
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


async def _make_razorpay_pack(
    session,
    user: User,
    *,
    order_id: str,
    credits: int = 200,
    paid_item_cents: int = 79900,
    status: str = "active",
) -> BillingCreditPack:
    pack = BillingCreditPack(
        user_id=user.id,
        provider="razorpay",
        provider_checkout_id=f"plink_{uuid4().hex[:10]}",
        provider_order_id=order_id,
        credits_purchased=credits,
        credits_remaining=credits,
        price_cents=paid_item_cents,
        currency="INR",
        paid_item_amount_cents=paid_item_cents,
        provider_order_total_cents=paid_item_cents,
        status=status,
        purchased_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=29),
    )
    session.add(pack)
    await session.commit()
    await session.refresh(pack)
    return pack


async def _make_razorpay_attempt(
    session, user: User, *, status: str, expires_in_minutes: int
) -> BillingCheckoutAttempt:
    attempt = BillingCheckoutAttempt(
        checkout_ref=f"ref_{uuid4().hex}",
        user_id=user.id,
        provider="razorpay",
        checkout_nonce_hash="x" * 64,
        credits=200,
        price_cents=79900,
        currency="INR",
        validity_days=30,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt


async def _set_cursor_start(
    session, last_order_id: str, *, provider: str = "lemonsqueezy"
) -> None:
    await session.execute(
        update(BillingReconciliationCursor)
        .where(BillingReconciliationCursor.provider == provider)
        .values(state={"lane2_last_order_id": last_order_id})
    )
    await session.commit()


# Fresh-session reads.


async def _cursor(maker, provider: str = "lemonsqueezy") -> BillingReconciliationCursor:
    async with maker() as db:
        return await db.scalar(
            select(BillingReconciliationCursor).where(
                BillingReconciliationCursor.provider == provider
            )
        )


async def _pack(maker, pack_id: UUID) -> BillingCreditPack:
    async with maker() as db:
        return await db.scalar(
            select(BillingCreditPack).where(BillingCreditPack.id == pack_id)
        )


async def _balance(maker, user_id: UUID) -> int:
    async with maker() as db:
        return await db.scalar(select(User.credit_balance).where(User.id == user_id))


async def _attempt_status(maker, attempt_id: UUID) -> str:
    async with maker() as db:
        return await db.scalar(
            select(BillingCheckoutAttempt.status).where(
                BillingCheckoutAttempt.id == attempt_id
            )
        )


# ---------------------------------------------------------------------------
# Lane 1 — inbox replay
# ---------------------------------------------------------------------------


async def test_lane1_replays_committed_received_inbox_row(
    session, db_maker, cleanup, fake_lemon
) -> None:
    row = BillingWebhookEvent(
        provider="lemonsqueezy",
        event_name="order_created",
        provider_object_type="orders",
        provider_object_id=f"order-{uuid4()}",
        payload_hash=uuid4().hex,
        status="received",
        normalized_payload={"event_name": "order_created", "custom": {}},
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    cleanup.webhooks.append(row.id)

    pool = _RecordingPool()
    await billing_worker.billing_reconcile({"redis": pool})

    # The received inbox row was re-enqueued under its deterministic dedup id.
    job_ids = [k.get("_job_id") for _a, k in pool.calls]
    assert f"billing_wh:{row.id}" in job_ids
    cursor = await _cursor(db_maker)
    assert cursor.last_successful_run_at > _EPOCH  # advanced on success


# ---------------------------------------------------------------------------
# Lane 2 — bounded provider re-read
# ---------------------------------------------------------------------------


async def test_lane2_processes_refund_by_exact_order_id(
    session, db_maker, cleanup, fake_lemon
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"zzzzrecon-{uuid4().hex}-001"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id
    await _set_cursor_start(session, order_id[:-1])  # start just below this order

    fake_lemon.set(
        order_id,
        LemonOrder(
            provider_order_id=order_id,
            status="refunded",
            refunded=True,
            refunded_amount_cents=900,
            total_cents=900,
        ),
    )

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert fake_lemon.calls == [order_id]  # re-read by exact id
    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 200
    assert p.status == "refunded"
    assert await _balance(db_maker, user_id) == 0


async def test_lane2_paid_order_is_a_noop(
    session, db_maker, cleanup, fake_lemon
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"zzzzrecon-{uuid4().hex}-001"
    pack = await _make_pack(session, user, order_id=order_id)
    pack_id, user_id = pack.id, user.id
    await _set_cursor_start(session, order_id[:-1])
    # default fake response is a still-paid order → no reversal.

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 0
    assert await _balance(db_maker, user_id) == 200


async def test_lane2_is_bounded_by_max_calls_per_run(
    session, db_maker, cleanup, fake_lemon, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "lemonsqueezy_reconcile_max_calls_per_run", 2)
    user = await _make_user(session, cleanup, balance=600)
    prefix = f"zzzzrecon-{uuid4().hex}"
    ids = [f"{prefix}-{n:03d}" for n in range(1, 4)]  # 3 packs, cap is 2
    for oid in ids:
        await _make_pack(session, user, order_id=oid)
    await _set_cursor_start(session, prefix)  # start just below the first pack

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    # Only the first two (cap) are fetched this run; the cursor stops at the 2nd.
    assert fake_lemon.calls == ids[:2]
    cursor = await _cursor(db_maker)
    assert cursor.state["lane2_last_order_id"] == ids[1]


async def test_lane2_backs_off_on_rate_limit_and_leaves_cursor(
    session, db_maker, cleanup, fake_lemon
) -> None:
    user = await _make_user(session, cleanup, balance=600)
    prefix = f"zzzzrecon-{uuid4().hex}"
    ids = [f"{prefix}-{n:03d}" for n in range(1, 4)]
    for oid in ids:
        await _make_pack(session, user, order_id=oid)
    await _set_cursor_start(session, prefix)
    # First order re-reads fine (paid), the second 429s → stop the lane.
    fake_lemon.set(ids[1], LemonSqueezyRateLimitError(5.0))

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert fake_lemon.calls == ids[:2]  # stopped at the 429, never reached the 3rd
    cursor = await _cursor(db_maker)
    assert cursor.state["lane2_last_order_id"] == ids[0]  # advanced only past success


async def test_lane2_stops_and_holds_cursor_on_provider_error(
    session, db_maker, cleanup, fake_lemon
) -> None:
    user = await _make_user(session, cleanup, balance=600)
    prefix = f"zzzzrecon-{uuid4().hex}"
    ids = [f"{prefix}-{n:03d}" for n in range(1, 3)]
    for oid in ids:
        await _make_pack(session, user, order_id=oid)
    await _set_cursor_start(session, prefix)
    fake_lemon.set(ids[0], LemonSqueezyError("boom 503"))

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert fake_lemon.calls == [ids[0]]
    cursor = await _cursor(db_maker)
    assert cursor.state["lane2_last_order_id"] == prefix  # unchanged (no success)


async def test_lane2_resets_cursor_after_full_scan(
    session, db_maker, cleanup, fake_lemon
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    order_id = f"zzzzrecon-{uuid4().hex}-001"
    await _make_pack(session, user, order_id=order_id)
    await _set_cursor_start(session, order_id[:-1])

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    cursor = await _cursor(db_maker)
    # Fewer than the cap returned → scan exhausted → cursor resets for continuity.
    assert cursor.state["lane2_last_order_id"] == ""


# ---------------------------------------------------------------------------
# No auto-grant — the hard security invariant
# ---------------------------------------------------------------------------


async def test_never_auto_grants_a_missing_order_created(
    session, db_maker, cleanup, fake_lemon
) -> None:
    # A paid checkout whose order_created was never committed: only an attempt
    # exists (no pack, no inbox row). Reconcile must NOT invent a grant.
    user = await _make_user(session, cleanup, balance=0)
    attempt = await _make_attempt(
        session, user, status="provider_created", expires_in_minutes=30
    )
    user_id = user.id

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    # No pack created, balance untouched, and lane 2 never even fetched (no pack).
    assert fake_lemon.calls == []
    assert await _balance(db_maker, user_id) == 0
    async with db_maker() as db:
        packs = await db.execute(
            select(BillingCreditPack).where(BillingCreditPack.user_id == user_id)
        )
        assert packs.scalars().all() == []
    # The attempt remains uncredited (still open within TTL).
    assert await _attempt_status(db_maker, attempt.id) == "provider_created"


# ---------------------------------------------------------------------------
# Lane 3 — checkout-attempt hygiene
# ---------------------------------------------------------------------------


async def test_lane3_expires_attempts_past_ttl(
    session, db_maker, cleanup, fake_lemon
) -> None:
    user = await _make_user(session, cleanup, balance=0)
    stale = await _make_attempt(
        session, user, status="provider_created", expires_in_minutes=-60
    )
    fresh = await _make_attempt(session, user, status="created", expires_in_minutes=60)

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert await _attempt_status(db_maker, stale.id) == "expired"
    assert await _attempt_status(db_maker, fresh.id) == "created"  # untouched


# ---------------------------------------------------------------------------
# Cursor advance-on-success / single-active-run
# ---------------------------------------------------------------------------


async def test_skips_cleanly_when_cursor_already_locked(
    session, db_maker, cleanup, fake_lemon
) -> None:
    # Hold the cursor row lock in a separate session, then run reconcile: the
    # NOWAIT claim must fail and the run must skip cleanly (no exception, no state
    # change).
    async with db_maker() as holder:
        await holder.execute(
            select(BillingReconciliationCursor)
            .where(BillingReconciliationCursor.provider == "lemonsqueezy")
            .with_for_update()
        )
        # lock held (transaction open) for the duration of this block
        await billing_worker.billing_reconcile({"redis": _RecordingPool()})
        await holder.rollback()

    cursor = await _cursor(db_maker)
    assert cursor.last_successful_run_at == _EPOCH  # skipped → unchanged


async def test_cursor_unchanged_on_run_failure(
    session, db_maker, cleanup, fake_lemon, monkeypatch
) -> None:
    # Force a lane to raise; the run must roll back (last_successful_run_at stays at
    # the baseline) and persist last_error without crashing the cron.
    async def _boom() -> int:
        raise RuntimeError("lane 3 exploded")

    monkeypatch.setattr(billing_worker, "_reconcile_lane3", _boom)

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    cursor = await _cursor(db_maker)
    assert cursor.last_successful_run_at == _EPOCH  # NOT advanced
    assert cursor.last_error is not None


async def test_cursor_advances_only_after_success(
    session, db_maker, cleanup, fake_lemon
) -> None:
    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    cursor = await _cursor(db_maker)
    assert cursor.last_successful_run_at > _EPOCH
    assert cursor.last_run_completed_at is not None
    assert cursor.last_error is None


# ---------------------------------------------------------------------------
# Razorpay lane 2 — per-provider re-read via get_payment (issue #44)
# ---------------------------------------------------------------------------


async def test_lane2_razorpay_refund_by_payment_id(
    session, db_maker, cleanup, fake_lemon, fake_razorpay
) -> None:
    # A razorpay pack whose refund the webhook path missed: lane 2 re-reads it by
    # payment id via get_payment and applies the proportional reversal — using the
    # razorpay cursor + budget, never lemon's.
    user = await _make_user(session, cleanup, balance=200)
    payment_id = f"zzzzrzp-{uuid4().hex}-001"
    pack = await _make_razorpay_pack(session, user, order_id=payment_id)
    pack_id, user_id = pack.id, user.id
    await _set_cursor_start(session, payment_id[:-1], provider="razorpay")

    fake_razorpay.set(
        payment_id,
        RazorpayPayment(
            payment_id=payment_id,
            status="captured",
            amount_cents=79900,
            amount_refunded_cents=79900,  # full refund
            refund_status="full",
        ),
    )

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert fake_razorpay.calls == [payment_id]  # re-read by exact id
    assert fake_lemon.calls == []  # lemon lane touched nothing
    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 200
    assert p.status == "refunded"
    assert await _balance(db_maker, user_id) == 0


async def test_lane2_razorpay_captured_payment_is_a_noop(
    session, db_maker, cleanup, fake_lemon, fake_razorpay
) -> None:
    user = await _make_user(session, cleanup, balance=200)
    payment_id = f"zzzzrzp-{uuid4().hex}-001"
    pack = await _make_razorpay_pack(session, user, order_id=payment_id)
    pack_id, user_id = pack.id, user.id
    await _set_cursor_start(session, payment_id[:-1], provider="razorpay")
    # default fake response is a captured, un-refunded payment → no reversal.

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    p = await _pack(db_maker, pack_id)
    assert p.credits_revoked == 0
    assert await _balance(db_maker, user_id) == 200


async def test_lane2_both_providers_interleave_independently(
    session, db_maker, cleanup, fake_lemon, fake_razorpay
) -> None:
    # One live lemon pack and one live razorpay pack, each refunded at the provider.
    # A single reconcile run re-reads each via its own service and advances each
    # cursor independently.
    lemon_user = await _make_user(session, cleanup, balance=200)
    rzp_user = await _make_user(session, cleanup, balance=200)
    lemon_order = f"zzzzlem-{uuid4().hex}-001"
    rzp_payment = f"zzzzrzp-{uuid4().hex}-001"
    lemon_pack = await _make_pack(session, lemon_user, order_id=lemon_order)
    rzp_pack = await _make_razorpay_pack(session, rzp_user, order_id=rzp_payment)
    await _set_cursor_start(session, lemon_order[:-1], provider="lemonsqueezy")
    await _set_cursor_start(session, rzp_payment[:-1], provider="razorpay")

    fake_lemon.set(
        lemon_order,
        LemonOrder(
            provider_order_id=lemon_order,
            status="refunded",
            refunded=True,
            refunded_amount_cents=900,
            total_cents=900,
        ),
    )
    fake_razorpay.set(
        rzp_payment,
        RazorpayPayment(
            payment_id=rzp_payment,
            status="captured",
            amount_cents=79900,
            amount_refunded_cents=79900,
            refund_status="full",
        ),
    )

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert fake_lemon.calls == [lemon_order]
    assert fake_razorpay.calls == [rzp_payment]
    assert (await _pack(db_maker, lemon_pack.id)).credits_revoked == 200
    assert (await _pack(db_maker, rzp_pack.id)).credits_revoked == 200
    assert await _balance(db_maker, lemon_user.id) == 0
    assert await _balance(db_maker, rzp_user.id) == 0


async def test_lane2_razorpay_backs_off_on_rate_limit_without_stopping_lemon(
    session, db_maker, cleanup, fake_lemon, fake_razorpay
) -> None:
    # A 429 from razorpay stops only razorpay's lane (its cursor holds at the last
    # success); lemon's lane in the same run is unaffected and advances normally.
    lemon_user = await _make_user(session, cleanup, balance=200)
    rzp_user = await _make_user(session, cleanup, balance=600)
    lemon_order = f"zzzzlem-{uuid4().hex}-001"
    lemon_pack = await _make_pack(session, lemon_user, order_id=lemon_order)
    await _set_cursor_start(session, lemon_order[:-1], provider="lemonsqueezy")

    prefix = f"zzzzrzp-{uuid4().hex}"
    ids = [f"{prefix}-{n:03d}" for n in range(1, 4)]
    for pid in ids:
        await _make_razorpay_pack(session, rzp_user, order_id=pid)
    await _set_cursor_start(session, prefix, provider="razorpay")
    # First razorpay payment re-reads fine, the second 429s → stop razorpay's lane.
    fake_razorpay.set(ids[1], RazorpayRateLimitError(5.0))
    fake_lemon.set(
        lemon_order,
        LemonOrder(
            provider_order_id=lemon_order,
            status="refunded",
            refunded=True,
            refunded_amount_cents=900,
            total_cents=900,
        ),
    )

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    # Razorpay stopped at the 429, cursor held at the first (only) success.
    assert fake_razorpay.calls == ids[:2]
    rzp_cursor = await _cursor(db_maker, "razorpay")
    assert rzp_cursor.state["lane2_last_order_id"] == ids[0]
    # Lemon lane unaffected: revoked and the run committed successfully.
    assert (await _pack(db_maker, lemon_pack.id)).credits_revoked == 200
    lemon_cursor = await _cursor(db_maker, "lemonsqueezy")
    assert lemon_cursor.last_successful_run_at > _EPOCH
    assert lemon_cursor.last_error is None


async def test_lane2_razorpay_bounded_by_its_own_budget(
    session, db_maker, cleanup, fake_lemon, fake_razorpay, monkeypatch
) -> None:
    # The razorpay lane obeys razorpay_reconcile_max_calls_per_run, not lemon's.
    monkeypatch.setattr(settings, "razorpay_reconcile_max_calls_per_run", 2)
    user = await _make_user(session, cleanup, balance=600)
    prefix = f"zzzzrzp-{uuid4().hex}"
    ids = [f"{prefix}-{n:03d}" for n in range(1, 4)]  # 3 packs, cap is 2
    for pid in ids:
        await _make_razorpay_pack(session, user, order_id=pid)
    await _set_cursor_start(session, prefix, provider="razorpay")

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert fake_razorpay.calls == ids[:2]  # capped this run
    cursor = await _cursor(db_maker, "razorpay")
    assert cursor.state["lane2_last_order_id"] == ids[1]


# ---------------------------------------------------------------------------
# All-cursor run lock + failure fan-out (D11, issue #44)
# ---------------------------------------------------------------------------


async def test_skips_cleanly_when_any_cursor_row_is_locked(
    session, db_maker, cleanup, fake_lemon, fake_razorpay
) -> None:
    # Holding ONLY the razorpay cursor row must make the whole tick skip — the run
    # claims every provider's row upfront under one NOWAIT lock (D11), so no lane
    # runs and the lemon cursor is left untouched.
    async with db_maker() as holder:
        await holder.execute(
            select(BillingReconciliationCursor)
            .where(BillingReconciliationCursor.provider == "razorpay")
            .with_for_update()
        )
        await billing_worker.billing_reconcile({"redis": _RecordingPool()})
        await holder.rollback()

    lemon_cursor = await _cursor(db_maker, "lemonsqueezy")
    assert lemon_cursor.last_successful_run_at == _EPOCH  # skipped → unchanged
    assert fake_lemon.calls == []


async def test_run_failure_stamps_last_error_on_every_cursor(
    session, db_maker, cleanup, fake_lemon, fake_razorpay, monkeypatch
) -> None:
    # A failed run rolls back and persists last_error on EVERY claimed cursor row
    # (not just lemon's). Regression guard for the post-rollback provider snapshot:
    # reading cursor.provider after the rollback would raise MissingGreenlet.
    async def _boom() -> int:
        raise RuntimeError("lane 3 exploded")

    monkeypatch.setattr(billing_worker, "_reconcile_lane3", _boom)

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    for provider in ("lemonsqueezy", "razorpay"):
        cursor = await _cursor(db_maker, provider)
        assert cursor.last_successful_run_at == _EPOCH  # NOT advanced
        assert cursor.last_error is not None


async def test_lane3_expiry_metric_labelled_per_provider(
    session, db_maker, cleanup, fake_lemon, fake_razorpay
) -> None:
    # An expired-attempt batch can span both providers; the BILLING_CHECKOUT_EXPIRED
    # metric is incremented per each attempt's own provider.
    user = await _make_user(session, cleanup, balance=0)
    lemon_stale = await _make_attempt(
        session, user, status="provider_created", expires_in_minutes=-60
    )
    rzp_stale = await _make_razorpay_attempt(
        session, user, status="provider_created", expires_in_minutes=-60
    )

    before_lemon = BILLING_CHECKOUT_EXPIRED.labels(provider="lemonsqueezy")._value.get()
    before_rzp = BILLING_CHECKOUT_EXPIRED.labels(provider="razorpay")._value.get()

    await billing_worker.billing_reconcile({"redis": _RecordingPool()})

    assert await _attempt_status(db_maker, lemon_stale.id) == "expired"
    assert await _attempt_status(db_maker, rzp_stale.id) == "expired"
    after_lemon = BILLING_CHECKOUT_EXPIRED.labels(provider="lemonsqueezy")._value.get()
    after_rzp = BILLING_CHECKOUT_EXPIRED.labels(provider="razorpay")._value.get()
    assert after_lemon - before_lemon == 1
    assert after_rzp - before_rzp == 1

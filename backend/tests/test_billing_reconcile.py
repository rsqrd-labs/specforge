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


@pytest.fixture(autouse=True)
async def reset_cursor(session: AsyncSession):
    """Reset the singleton reconcile cursor to a clean baseline around each test."""
    await session.execute(
        update(BillingReconciliationCursor)
        .where(BillingReconciliationCursor.provider == "lemonsqueezy")
        .values(
            last_successful_run_at=_EPOCH,
            last_run_started_at=None,
            last_run_completed_at=None,
            last_error=None,
            state={},
        )
    )
    await session.commit()
    yield
    await session.execute(
        update(BillingReconciliationCursor)
        .where(BillingReconciliationCursor.provider == "lemonsqueezy")
        .values(
            last_successful_run_at=_EPOCH,
            last_run_started_at=None,
            last_run_completed_at=None,
            last_error=None,
            state={},
        )
    )
    await session.commit()


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


async def _set_cursor_start(session, last_order_id: str) -> None:
    await session.execute(
        update(BillingReconciliationCursor)
        .where(BillingReconciliationCursor.provider == "lemonsqueezy")
        .values(state={"lane2_last_order_id": last_order_id})
    )
    await session.commit()


# Fresh-session reads.


async def _cursor(maker) -> BillingReconciliationCursor:
    async with maker() as db:
        return await db.scalar(
            select(BillingReconciliationCursor).where(
                BillingReconciliationCursor.provider == "lemonsqueezy"
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

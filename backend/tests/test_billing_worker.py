"""Integration tests for the durable billing webhook worker (Phase 22 — T-298).

T-298's deliverable is DB-concurrency semantics — ``SELECT … FOR UPDATE``, the
``processed`` short-circuit, ``FOR UPDATE SKIP LOCKED`` reclaim, the
separate-transaction failed-state, and ``billing_wh:{id}`` dedup. A fake session
cannot exercise any of that, so these are **real-Postgres** tests gated on
``TEST_DATABASE_URL`` (set in CI): they skip locally and run in CI, mirroring the
other worker integration suites (``test_push_repo`` / ``test_increment_sync``).

The worker functions call ``AsyncSessionLocal()`` directly, which is bound to
``settings.database_url`` — the same Postgres the fixtures set up — so no session
injection is needed. The enqueue side is a recording fake pool (the DB logic is
real; only the arq target is faked, which is what we assert).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import User
from models.billing_checkout_attempt import BillingCheckoutAttempt
from models.billing_webhook_event import BillingWebhookEvent
from services import billing_worker
from services.queue import JOB_MAX_TRIES, QueueUnavailableError

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason=(
            "TEST_DATABASE_URL not set — Postgres worker integration test skipped. "
            "Runs in CI against the test database. T-298."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_maker(monkeypatch) -> async_sessionmaker:
    """A per-test NullPool sessionmaker bound to the current event loop.

    The worker calls the module-level ``AsyncSessionLocal`` directly (no DI), and
    its pooled asyncpg connections bind to the loop that first created them — fatal
    under pytest-asyncio's per-test loops. Pointing ``billing_worker.AsyncSessionLocal``
    at a fresh NullPool maker per test keeps every connection on the test's loop.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(billing_worker, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()


@pytest.fixture
async def session(db_maker: async_sessionmaker) -> AsyncSession:
    async with db_maker() as db:
        yield db


@pytest.fixture
async def user(session: AsyncSession) -> User:
    u = User(
        email=f"billing-worker-{uuid4()}@example.com",
        google_id=f"google-{uuid4()}",
        name="Billing Worker Tester",
        avatar_url=None,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    yield u
    await session.execute(delete(User).where(User.id == u.id))
    await session.commit()


@pytest.fixture
async def cleanup_events(session: AsyncSession):
    """Track inserted webhook-event / attempt ids and delete them after the test."""
    event_ids: list[UUID] = []
    attempt_ids: list[UUID] = []
    yield event_ids, attempt_ids
    if event_ids:
        await session.execute(
            delete(BillingWebhookEvent).where(BillingWebhookEvent.id.in_(event_ids))
        )
    if attempt_ids:
        await session.execute(
            delete(BillingCheckoutAttempt).where(
                BillingCheckoutAttempt.id.in_(attempt_ids)
            )
        )
    await session.commit()


@pytest.fixture(autouse=True)
def restore_handlers():
    """Snapshot/restore the event-handler registry around each test."""
    snapshot = dict(billing_worker._EVENT_HANDLERS)
    yield
    billing_worker._EVENT_HANDLERS.clear()
    billing_worker._EVENT_HANDLERS.update(snapshot)


class _RecordingPool:
    """Fake arq pool recording enqueue_job calls (and optional outage)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._fail = fail

    async def enqueue_job(self, *args: Any, **kwargs: Any):
        if self._fail:
            raise ConnectionError("redis down")
        self.calls.append((args, kwargs))

        class _Job:
            job_id = kwargs.get("_job_id")

        return _Job()


async def _insert_event(
    session: AsyncSession,
    cleanup,
    *,
    event_name: str = "order_created",
    status: str = "received",
    retry_count: int = 0,
    received_at: datetime | None = None,
    processed_at: datetime | None = None,
) -> BillingWebhookEvent:
    event_ids, _ = cleanup
    row = BillingWebhookEvent(
        provider="lemonsqueezy",
        event_name=event_name,
        provider_object_type="orders",
        provider_object_id=f"order-{uuid4()}",
        payload_hash=uuid4().hex,
        status=status,
        retry_count=retry_count,
        normalized_payload={"event_name": event_name, "custom": {}},
        processed_at=processed_at,
    )
    session.add(row)
    await session.flush()
    if received_at is not None:
        row.received_at = received_at
    await session.commit()
    await session.refresh(row)
    event_ids.append(row.id)
    return row


async def _reload(session: AsyncSession, wid: UUID) -> BillingWebhookEvent:
    session.expire_all()
    return await session.scalar(
        select(BillingWebhookEvent).where(BillingWebhookEvent.id == wid)
    )


# ---------------------------------------------------------------------------
# billing_process_webhook — claim / dispatch / failure
# ---------------------------------------------------------------------------


async def test_acks_unhandled_non_order_event(session, cleanup_events) -> None:
    row = await _insert_event(
        session, cleanup_events, event_name="subscription_created"
    )
    await billing_worker.billing_process_webhook({}, str(row.id))
    reloaded = await _reload(session, row.id)
    assert reloaded.status == "processed"
    assert reloaded.processed_at is not None


async def test_short_circuits_already_processed(session, cleanup_events) -> None:
    row = await _insert_event(
        session,
        cleanup_events,
        event_name="subscription_created",
        status="processed",
    )

    async def _boom(ctx, wid):  # pragma: no cover - must never be called
        raise AssertionError("handler must not run for a processed row")

    billing_worker.register_event_handler("lemonsqueezy", "subscription_created", _boom)
    await billing_worker.billing_process_webhook({}, str(row.id))
    reloaded = await _reload(session, row.id)
    assert reloaded.status == "processed"


async def test_success_via_registered_handler(session, cleanup_events) -> None:
    row = await _insert_event(session, cleanup_events, event_name="order_created")
    calls = {"n": 0}

    async def _handler(ctx, wid):
        calls["n"] += 1
        # The handler owns its transaction + the 'processed' transition.
        async with billing_worker.AsyncSessionLocal() as db:
            r = await db.scalar(
                select(BillingWebhookEvent).where(BillingWebhookEvent.id == UUID(wid))
            )
            r.status = "processed"
            r.processed_at = datetime.now(UTC)
            await db.commit()

    billing_worker.register_event_handler("lemonsqueezy", "order_created", _handler)
    await billing_worker.billing_process_webhook({}, str(row.id))
    assert calls["n"] == 1
    reloaded = await _reload(session, row.id)
    assert reloaded.status == "processed"


async def test_failure_persists_failed_in_separate_transaction(
    session, cleanup_events
) -> None:
    row = await _insert_event(session, cleanup_events, event_name="order_created")

    async def _handler(ctx, wid):
        # Mutate inside the handler's own transaction, then raise → that
        # transaction rolls back, but the separate failed-state tx must persist.
        async with billing_worker.AsyncSessionLocal() as db:
            r = await db.scalar(
                select(BillingWebhookEvent).where(BillingWebhookEvent.id == UUID(wid))
            )
            r.status = "processed"  # side effect that must be rolled back
            await db.flush()
            raise RuntimeError("forced side-effect failure")

    billing_worker.register_event_handler("lemonsqueezy", "order_created", _handler)

    with pytest.raises(RuntimeError):
        await billing_worker.billing_process_webhook({}, str(row.id))

    reloaded = await _reload(session, row.id)
    assert reloaded.status == "failed"  # NOT 'processed' — side effect rolled back
    assert reloaded.retry_count == 1
    assert "forced side-effect failure" in (reloaded.last_error or "")


async def test_order_event_without_handler_fails_loud(session, cleanup_events) -> None:
    # order_created is registered at import by T-299; exercise the genuine
    # no-handler branch by removing it (the autouse restore_handlers fixture
    # restores the registry afterwards).
    billing_worker._EVENT_HANDLERS.pop(("lemonsqueezy", "order_created"), None)
    row = await _insert_event(session, cleanup_events, event_name="order_created")
    with pytest.raises(RuntimeError):
        await billing_worker.billing_process_webhook({}, str(row.id))
    reloaded = await _reload(session, row.id)
    assert reloaded.status == "failed"
    assert reloaded.retry_count == 1


async def test_claim_flips_received_to_processing_before_dispatch(
    session, cleanup_events
) -> None:
    row = await _insert_event(session, cleanup_events, event_name="order_created")
    seen_status = {}

    async def _handler(ctx, wid):
        async with billing_worker.AsyncSessionLocal() as db:
            r = await db.scalar(
                select(BillingWebhookEvent).where(BillingWebhookEvent.id == UUID(wid))
            )
            seen_status["at_dispatch"] = r.status  # committed 'processing'
            r.status = "processed"
            r.processed_at = datetime.now(UTC)
            await db.commit()

    billing_worker.register_event_handler("lemonsqueezy", "order_created", _handler)
    await billing_worker.billing_process_webhook({}, str(row.id))
    assert seen_status["at_dispatch"] == "processing"


# ---------------------------------------------------------------------------
# billing_process_pending_webhooks — recovery sweep
# ---------------------------------------------------------------------------


async def test_sweep_enqueues_orphaned_received(session, cleanup_events) -> None:
    """Queue-outage recovery: a committed 'received' row is re-enqueued (≤60s)."""
    row = await _insert_event(session, cleanup_events, status="received")
    pool = _RecordingPool()
    await billing_worker.billing_process_pending_webhooks({"redis": pool})

    enqueued = [c for c in pool.calls if str(row.id) in c[0]]
    assert len(enqueued) == 1
    args, kwargs = enqueued[0]
    assert args[0] == "billing_process_webhook"
    assert args[1] == str(row.id)
    assert kwargs["_job_id"] == f"billing_wh:{row.id}"


async def test_sweep_reclaims_stale_processing(session, cleanup_events) -> None:
    stale_at = datetime.now(UTC) - timedelta(minutes=10)
    row = await _insert_event(
        session, cleanup_events, status="processing", received_at=stale_at
    )
    pool = _RecordingPool()
    await billing_worker.billing_process_pending_webhooks({"redis": pool})

    reloaded = await _reload(session, row.id)
    assert reloaded.status == "failed"
    assert reloaded.retry_count == 1
    assert "reclaimed" in (reloaded.last_error or "")
    # Reclaimed rows are re-enqueued in the same pass.
    assert any(str(row.id) in c[0] for c in pool.calls)


async def test_sweep_skips_fresh_processing(session, cleanup_events) -> None:
    row = await _insert_event(
        session,
        cleanup_events,
        status="processing",
        received_at=datetime.now(UTC),
    )
    pool = _RecordingPool()
    await billing_worker.billing_process_pending_webhooks({"redis": pool})

    reloaded = await _reload(session, row.id)
    assert reloaded.status == "processing"  # not reclaimed
    assert not any(str(row.id) in c[0] for c in pool.calls)


async def test_sweep_skips_exhausted_failed(session, cleanup_events) -> None:
    row = await _insert_event(
        session, cleanup_events, status="failed", retry_count=JOB_MAX_TRIES
    )
    pool = _RecordingPool()
    await billing_worker.billing_process_pending_webhooks({"redis": pool})
    assert not any(str(row.id) in c[0] for c in pool.calls)


async def test_sweep_reenqueues_retryable_failed(session, cleanup_events) -> None:
    row = await _insert_event(session, cleanup_events, status="failed", retry_count=1)
    pool = _RecordingPool()
    await billing_worker.billing_process_pending_webhooks({"redis": pool})
    assert any(str(row.id) in c[0] for c in pool.calls)


async def test_sweep_defers_pack_not_yet_granted_to_reconcile(
    session, cleanup_events
) -> None:
    """A refund parked on its out-of-order grant is skipped by the 60s sweep but
    re-driven by the 15-minute reconcile lane (T-308 review hardening)."""
    row = await _insert_event(
        session, cleanup_events, event_name="order_refunded", status="received"
    )
    row.last_error = billing_worker._PACK_NOT_YET_GRANTED
    await session.commit()

    # 60s sweep: the deferred row is NOT enqueued.
    pool = _RecordingPool()
    await billing_worker.billing_process_pending_webhooks({"redis": pool})
    assert not any(str(row.id) in c[0] for c in pool.calls)

    # Direct claim with the sweep's exclusion drops it; the default (reconcile
    # lane 1) still returns it so it keeps retrying on the slow cadence.
    swept = await billing_worker._claim_pending_ids(
        reclaim_stale=False, exclude_deferred_retries=True
    )
    assert row.id not in swept
    reconciled = await billing_worker._claim_pending_ids(reclaim_stale=False)
    assert row.id in reconciled


async def test_sweep_includes_fresh_refund_without_last_error(
    session, cleanup_events
) -> None:
    """A first-delivery refund (no last_error) is never deferred — the sweep drives
    it immediately even with the exclusion on."""
    row = await _insert_event(
        session, cleanup_events, event_name="order_refunded", status="received"
    )
    swept = await billing_worker._claim_pending_ids(
        reclaim_stale=False, exclude_deferred_retries=True
    )
    assert row.id in swept


async def test_sweep_dedup_job_id_matches_request_path(session, cleanup_events) -> None:
    """The sweep's job id equals the request-path id, so arq collapses them."""
    row = await _insert_event(session, cleanup_events, status="received")
    pool = _RecordingPool()
    await billing_worker.billing_process_pending_webhooks({"redis": pool})
    job_ids = [c[1]["_job_id"] for c in pool.calls if str(row.id) in c[0]]
    assert job_ids == [f"billing_wh:{row.id}"]


async def test_sweep_swallows_queue_outage(session, cleanup_events) -> None:
    """A Redis outage during enqueue is caught — the cron never raises."""
    await _insert_event(session, cleanup_events, status="received")
    pool = _RecordingPool(fail=True)
    # Must not raise (enqueue() wraps the failure as QueueUnavailableError, which
    # the sweep catches and logs).
    await billing_worker.billing_process_pending_webhooks({"redis": pool})


async def test_enqueue_helper_raises_queue_unavailable_on_outage() -> None:
    """Guard: the queue helper surfaces a Redis outage as QueueUnavailableError."""
    from services.queue import enqueue

    pool = _RecordingPool(fail=True)
    with pytest.raises(QueueUnavailableError):
        await enqueue("billing_process_webhook", "x", job_id="billing_wh:x", pool=pool)


# ---------------------------------------------------------------------------
# billing_reconcile — Lane 1 inbox replay
# ---------------------------------------------------------------------------


async def test_reconcile_replays_received(session, cleanup_events) -> None:
    row = await _insert_event(session, cleanup_events, status="received")
    pool = _RecordingPool()
    await billing_worker.billing_reconcile({"redis": pool})
    assert any(str(row.id) in c[0] for c in pool.calls)


# ---------------------------------------------------------------------------
# purge_billing_events — retention
# ---------------------------------------------------------------------------


async def test_purge_deletes_terminal_old_rows_keeps_recent(
    session, cleanup_events, user
) -> None:
    event_ids, attempt_ids = cleanup_events
    old = datetime.now(UTC) - timedelta(days=40)
    recent = datetime.now(UTC)

    # Old processed webhook event → deleted; recent processed → kept.
    old_processed = await _insert_event(
        session,
        cleanup_events,
        event_name="order_created",
        status="processed",
        processed_at=old,
    )
    recent_processed = await _insert_event(
        session,
        cleanup_events,
        event_name="order_created",
        status="processed",
        processed_at=recent,
    )
    # An old 'received' row must be kept (not terminal).
    old_received = await _insert_event(
        session, cleanup_events, status="received", received_at=old
    )

    # Old terminal attempt → deleted; recent active attempt → kept.
    old_attempt = await _make_attempt(
        session, cleanup_events, user.id, status="expired", created_at=old
    )
    recent_attempt = await _make_attempt(
        session, cleanup_events, user.id, status="expired", created_at=recent
    )
    live_attempt = await _make_attempt(
        session, cleanup_events, user.id, status="created", created_at=old
    )

    # Capture ids as plain values BEFORE the purge — never touch the (about to be
    # expired) ORM attributes afterwards, which would trigger a sync lazy-load.
    old_processed_id = old_processed.id
    recent_processed_id = recent_processed.id
    old_received_id = old_received.id
    old_attempt_id = old_attempt.id
    recent_attempt_id = recent_attempt.id
    live_attempt_id = live_attempt.id

    await billing_worker.purge_billing_events({})

    remaining_events = set(
        (
            await session.execute(
                select(BillingWebhookEvent.id).where(
                    BillingWebhookEvent.id.in_(event_ids)
                )
            )
        ).scalars()
    )
    assert old_processed_id not in remaining_events
    assert recent_processed_id in remaining_events
    assert old_received_id in remaining_events  # 'received' is not terminal

    remaining_attempts = set(
        (
            await session.execute(
                select(BillingCheckoutAttempt.id).where(
                    BillingCheckoutAttempt.id.in_(attempt_ids)
                )
            )
        ).scalars()
    )
    assert old_attempt_id not in remaining_attempts
    assert recent_attempt_id in remaining_attempts
    assert live_attempt_id in remaining_attempts  # 'created' is not terminal


async def _make_attempt(
    session: AsyncSession,
    cleanup,
    user_id: UUID,
    *,
    status: str,
    created_at: datetime,
) -> BillingCheckoutAttempt:
    _, attempt_ids = cleanup
    attempt = BillingCheckoutAttempt(
        checkout_ref=f"ref-{uuid4()}",
        user_id=user_id,
        provider="lemonsqueezy",
        checkout_nonce_hash=uuid4().hex,
        credits=200,
        price_cents=900,
        currency="USD",
        validity_days=30,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    session.add(attempt)
    await session.flush()
    attempt.created_at = created_at
    await session.commit()
    await session.refresh(attempt)
    attempt_ids.append(attempt.id)
    return attempt

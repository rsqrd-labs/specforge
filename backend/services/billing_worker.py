"""Durable billing-webhook processing (Phase 22 — T-298).

The arq-side half of the Lemon Squeezy webhook pipeline. The request path
(T-297) verifies + sanitises an inbound order event into a durable
``billing_webhook_events`` inbox row and enqueues by row id; everything money- or
state-mutating happens **here**, on the worker, exactly once under retries.

This module owns the durable scaffolding:

  * :func:`billing_process_webhook` — claim a single inbox row (``SELECT … FOR
    UPDATE``), short-circuit if already ``processed``, mark ``processing`` in its
    own committed transaction (the durable claim + the reclaim clock), dispatch by
    ``event_name``, and on failure persist ``failed``/``retry_count``/``last_error``
    in a **separate** committed transaction before re-raising (so the rollback of
    side effects never also discards the failed state — R14).
  * :func:`billing_process_pending_webhooks` — the 60s recovery sweep: re-enqueue
    committed ``received`` rows the queue lost, retryable ``failed`` rows, and
    ``processing`` rows a crashed worker abandoned (reclaimed → ``failed`` after
    5 minutes). ``FOR UPDATE SKIP LOCKED`` + the deterministic ``billing_wh:{id}``
    job id mean a live worker's lock is the liveness signal and an in-flight
    wrapper-retry is never double-driven.
  * :func:`billing_reconcile` — the 15-minute backstop. T-298 implements **Lane 1**
    (inbox replay, sharing the sweep's logic); T-301 layers the cursor-locked
    provider-check (Lane 2) and checkout-attempt hygiene (Lane 3) on top.
  * :func:`purge_billing_events` — daily retention purge bounding the inbox and the
    terminal checkout attempts.

The per-``event_name`` money handlers (``order_created`` → T-299, ``order_refunded``
→ T-300) register themselves in :data:`_EVENT_HANDLERS` via
:func:`register_event_handler`; this task ships the registry empty. The
``arq``-registered wrappers and cron schedules live in ``worker.py``.

Handler contract (what T-299/T-300 must conform to)
---------------------------------------------------
A handler is ``async def handler(ctx, webhook_event_id: str) -> None``. It is
invoked by :func:`billing_process_webhook` **after** the inbox row has been
committed to ``processing``. It:
  * owns its own transaction(s) — opens its own session, does the money mutation,
    marks the row ``processed`` / ``processed_at``, and commits (so it can run any
    post-commit step such as the credit-cache invalidation);
  * **must be idempotent** — the sweep/reconcile can re-invoke it for the same row,
    so a provider-order/checkout uniqueness conflict must reload the existing pack,
    mark the row ``processed``, and write no second grant;
  * on raise, leaves the generic processor to persist the ``failed`` state in a
    separate committed transaction and schedule the arq retry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import delete, select, update

from database import AsyncSessionLocal
from models.billing_checkout_attempt import BillingCheckoutAttempt
from models.billing_webhook_event import BillingWebhookEvent
from services.queue import JOB_MAX_TRIES, QueueUnavailableError, enqueue

logger = structlog.get_logger(__name__)

# The inbox job name + the deterministic dedup job-id prefix. Shared verbatim with
# the request-path enqueue (T-297) so the wrapper-retry and the sweep collapse to a
# single in-flight job per row.
_PROCESS_JOB = "billing_process_webhook"
_JOB_ID_PREFIX = "billing_wh:"

# Order events carry money semantics and MUST have a registered handler before
# Lemon is enabled (T-299/T-300). Any other verified event is acknowledged as a
# no-op (we will never grant for it).
_ORDER_EVENTS = frozenset({"order_created", "order_refunded"})

# A 'processing' row whose claim is older than this is treated as abandoned by a
# crashed worker and reclaimed. ``received_at`` is the reclaim clock (the only
# timestamp on the row; the pending partial index is on (status, received_at)).
# 5 minutes is far beyond normal processing (seconds), so a live, fast handler is
# never reclaimed — and ``FOR UPDATE SKIP LOCKED`` skips a row a live worker still
# holds, making the lock the primary liveness signal and the clock the backstop.
_STALE_PROCESSING_MINUTES = 5

# Bounded batch sizes so a single cron tick can never run unboundedly.
_SWEEP_BATCH = 100
_PURGE_BATCH = 1000

# Terminal rows older than this are safe to delete (R9 / DC5). Generous relative
# to the provider redelivery window so dedup protection is never lost early.
_RETENTION_DAYS = 30

# A money/state handler for one event_name. See the module "Handler contract".
EventHandler = Callable[[dict, str], Awaitable[None]]

# Populated by T-299 (order_created) and T-300 (order_refunded). Empty here.
_EVENT_HANDLERS: dict[str, EventHandler] = {}


def register_event_handler(event_name: str, handler: EventHandler) -> None:
    """Register the money/state handler for ``event_name`` (T-299/T-300)."""
    _EVENT_HANDLERS[event_name] = handler


def _now() -> datetime:
    return datetime.now(UTC)


def _format_error(exc: BaseException) -> str:
    """A bounded, secret-free error string for ``last_error`` (no raw payload)."""
    return f"{type(exc).__name__}: {exc}"[:2000]


# ---------------------------------------------------------------------------
# The durable processor
# ---------------------------------------------------------------------------


async def billing_process_webhook(ctx: dict, webhook_event_id: str) -> None:
    """Process one inbox row exactly once (the body of the arq job).

    Claims the row (``FOR UPDATE``), short-circuits a row already ``processed``,
    marks ``processing`` and **commits** (durable claim), then dispatches. On any
    failure it rolls back the side effects, persists ``failed`` + ``retry_count`` +
    ``last_error`` in a SEPARATE committed transaction, and re-raises so the
    ``billing_job`` wrapper schedules the arq retry.
    """
    wid = UUID(webhook_event_id)

    # 1. Durable claim. Lock the row, short-circuit if already done, flip to
    #    'processing' and commit so the claim (and the reclaim clock) survives a
    #    crash and a concurrent worker sees it taken.
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(BillingWebhookEvent)
            .where(BillingWebhookEvent.id == wid)
            .with_for_update()
        )
        if row is None:
            logger.warning("billing.process.row_missing", webhook_event_id=str(wid))
            return
        if row.status == "processed":
            logger.info("billing.process.already_processed", webhook_event_id=str(wid))
            return
        row.status = "processing"
        await db.commit()

    # 2. Dispatch. On success the handler (or the no-op ack) marks the row
    #    'processed'. On failure persist the failed state separately, then re-raise.
    try:
        await _dispatch_claimed(ctx, wid)
    except Exception as exc:
        await _persist_failed(wid, exc)
        raise


async def _dispatch_claimed(ctx: dict, wid: UUID) -> None:
    """Route a claimed row to its handler, or ack/raise when none is registered."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(BillingWebhookEvent).where(BillingWebhookEvent.id == wid)
        )
        if row is None or row.status == "processed":
            return
        event_name = row.event_name

    handler = _EVENT_HANDLERS.get(event_name)
    if handler is not None:
        # The handler owns its transaction and the 'processed' transition.
        await handler(ctx, str(wid))
        return

    if event_name in _ORDER_EVENTS:
        # Money event with no handler yet (pre-T-299/T-300). This is unreachable
        # while Lemon is dormant — the signature verifier fails closed with no
        # secret, so no order rows can exist. Fail loud (it dead-letters and is
        # visible/recoverable) rather than silently acking a paid order.
        raise RuntimeError(f"no handler registered for order event {event_name!r}")

    # An event we will never act on (subscription_*, license_*, …) — ack it.
    await _mark_processed(wid)
    logger.info("billing.process.acked_unhandled", event_name=event_name)


async def _mark_processed(wid: UUID) -> None:
    """Mark a row ``processed`` (used for the no-op ack path)."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(BillingWebhookEvent)
            .where(BillingWebhookEvent.id == wid)
            .with_for_update()
        )
        if row is None or row.status == "processed":
            return
        row.status = "processed"
        row.processed_at = _now()
        await db.commit()


async def _persist_failed(wid: UUID, exc: BaseException) -> None:
    """Persist ``failed``/``retry_count``/``last_error`` in a SEPARATE committed tx.

    Non-negotiable (R14): the side-effect transaction has already rolled back, so
    the failed state must be written in its own transaction or a crash would lose
    it and the row would look stuck ``processing`` until the 5-minute reclaim.
    """
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(BillingWebhookEvent)
            .where(BillingWebhookEvent.id == wid)
            .with_for_update()
        )
        if row is None:
            return
        row.status = "failed"
        row.retry_count = (row.retry_count or 0) + 1
        row.last_error = _format_error(exc)
        await db.commit()
    logger.warning("billing.process.failed", webhook_event_id=str(wid))


# ---------------------------------------------------------------------------
# The 60s recovery sweep
# ---------------------------------------------------------------------------


async def billing_process_pending_webhooks(ctx: dict) -> None:
    """Re-enqueue stuck/orphaned inbox rows (the 60s recovery cron).

    Plain cron (catch + log — never raises): reclaims ``processing`` rows abandoned
    for more than 5 minutes (→ ``failed``, ``retry_count += 1``), then re-enqueues
    committed ``received`` rows and retryable ``failed`` rows. Uses ``FOR UPDATE
    SKIP LOCKED`` + a bounded batch and the deterministic ``billing_wh:{id}`` job id
    so an in-flight wrapper-retry is never double-driven. Never fetches from Lemon.
    """
    try:
        ids = await _claim_pending_ids(reclaim_stale=True)
        await _enqueue_ids(ctx, ids)
        if ids:
            logger.info("billing.sweep.enqueued", count=len(ids))
    except Exception:  # pragma: no cover - best-effort; the next tick retries
        logger.exception("billing.sweep.failed")


async def billing_reconcile(ctx: dict) -> None:
    """15-minute reconciliation backstop (cron; catch + log).

    T-298 ships **Lane 1 — inbox replay**: re-enqueue committed ``received``,
    retryable ``failed``, and reclaimed stale ``processing`` rows (the inbox row
    carries the signed proof, so this is the only safe automatic recovery). T-301
    adds Lane 2 (cursor-locked, bounded provider re-read for refund/fraud) and
    Lane 3 (checkout-attempt hygiene); it must **never** auto-grant from provider
    listing/email/receipt/amount.
    """
    try:
        ids = await _claim_pending_ids(reclaim_stale=True)
        await _enqueue_ids(ctx, ids)
        if ids:
            logger.info("billing.reconcile.replayed", count=len(ids))
    except Exception:  # pragma: no cover - best-effort; the next tick retries
        logger.exception("billing.reconcile.failed")


async def _claim_pending_ids(*, reclaim_stale: bool) -> list[UUID]:
    """Reclaim stale ``processing`` rows, then return pending ids to re-enqueue.

    One transaction: lock + reclaim abandoned ``processing`` rows, then select the
    pending set (``received`` ∪ retryable ``failed``, which now includes the
    just-reclaimed rows). ``FOR UPDATE SKIP LOCKED`` skips rows a live worker holds.
    """
    async with AsyncSessionLocal() as db:
        if reclaim_stale:
            cutoff = _now() - timedelta(minutes=_STALE_PROCESSING_MINUTES)
            stale = (
                (
                    await db.execute(
                        select(BillingWebhookEvent.id)
                        .where(
                            BillingWebhookEvent.status == "processing",
                            BillingWebhookEvent.received_at < cutoff,
                        )
                        .order_by(BillingWebhookEvent.received_at)
                        .limit(_SWEEP_BATCH)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            if stale:
                await db.execute(
                    update(BillingWebhookEvent)
                    .where(BillingWebhookEvent.id.in_(stale))
                    .values(
                        status="failed",
                        retry_count=BillingWebhookEvent.retry_count + 1,
                        last_error=(
                            "reclaimed: processing exceeded "
                            f"{_STALE_PROCESSING_MINUTES} minutes"
                        ),
                    )
                )

        pending = (
            (
                await db.execute(
                    select(BillingWebhookEvent.id)
                    .where(
                        (BillingWebhookEvent.status == "received")
                        | (
                            (BillingWebhookEvent.status == "failed")
                            & (BillingWebhookEvent.retry_count < JOB_MAX_TRIES)
                        )
                    )
                    .order_by(BillingWebhookEvent.received_at)
                    .limit(_SWEEP_BATCH)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        await db.commit()
    return list(pending)


async def _enqueue_ids(ctx: dict, ids: list[UUID]) -> None:
    """Enqueue each id under its deterministic dedup job id (best-effort)."""
    pool = ctx.get("redis")
    for wid in ids:
        try:
            await enqueue(
                _PROCESS_JOB,
                str(wid),
                job_id=f"{_JOB_ID_PREFIX}{wid}",
                pool=pool,
            )
        except QueueUnavailableError:
            # Redis is unreachable — stop this run; the next tick retries the
            # whole pending set (rows stay 'received'/'failed').
            logger.warning("billing.sweep.queue_unavailable")
            return


# ---------------------------------------------------------------------------
# Retention purge
# ---------------------------------------------------------------------------


async def purge_billing_events(ctx: dict) -> None:
    """Daily: bound the inbox + terminal checkout-attempt growth (cron; catch+log).

    Deletes terminal ``processed`` ``billing_webhook_events`` (by ``processed_at``)
    and terminal (``expired``/``failed``/``completed``) ``billing_checkout_attempts``
    (by ``created_at``) older than the retention window, in bounded batches.
    """
    try:
        cutoff = _now() - timedelta(days=_RETENTION_DAYS)
        async with AsyncSessionLocal() as db:
            webhook_ids = (
                (
                    await db.execute(
                        select(BillingWebhookEvent.id)
                        .where(
                            BillingWebhookEvent.status == "processed",
                            BillingWebhookEvent.processed_at < cutoff,
                        )
                        .limit(_PURGE_BATCH)
                    )
                )
                .scalars()
                .all()
            )
            if webhook_ids:
                await db.execute(
                    delete(BillingWebhookEvent).where(
                        BillingWebhookEvent.id.in_(webhook_ids)
                    )
                )

            attempt_ids = (
                (
                    await db.execute(
                        select(BillingCheckoutAttempt.id)
                        .where(
                            BillingCheckoutAttempt.status.in_(
                                ("expired", "failed", "completed")
                            ),
                            BillingCheckoutAttempt.created_at < cutoff,
                        )
                        .limit(_PURGE_BATCH)
                    )
                )
                .scalars()
                .all()
            )
            if attempt_ids:
                await db.execute(
                    delete(BillingCheckoutAttempt).where(
                        BillingCheckoutAttempt.id.in_(attempt_ids)
                    )
                )
            await db.commit()
        logger.info(
            "billing.purge.done",
            webhook_events=len(webhook_ids),
            checkout_attempts=len(attempt_ids),
        )
    except Exception:  # pragma: no cover - best-effort; the next daily tick retries
        logger.exception("billing.purge.failed")

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

The per-``event_name`` money handlers register themselves in :data:`_EVENT_HANDLERS`
via :func:`register_event_handler` at module import: ``order_created`` (T-299) is
wired below; ``order_refunded`` (T-300) joins it. The ``arq``-registered wrappers and
cron schedules live in ``worker.py``.

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
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from config import settings
from database import AsyncSessionLocal
from models import User
from models.billing_checkout_attempt import BillingCheckoutAttempt
from models.billing_credit_pack import BillingCreditPack
from models.billing_webhook_event import BillingWebhookEvent
from services.credit_service import credit_service
from services.observability import (
    BILLING_CHECKOUT_COMPLETED,
    BILLING_CREDITS_GRANTED,
    BILLING_PURCHASE_REVENUE_CENTS,
)
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


# ---------------------------------------------------------------------------
# order_created — grant credits for a verified, proof-matched paid order (T-299)
# ---------------------------------------------------------------------------
#
# Validation and the grant are anchored to the checkout-attempt SNAPSHOT
# (``attempt.credits`` / ``attempt.price_cents`` / ``attempt.currency`` /
# ``attempt.validity_days``), never live ``LEMONSQUEEZY_*`` config (Plan §25 DC6) —
# a config change between checkout creation and the webhook must not break or
# mis-price an in-flight purchase. Ownership is proven ONLY by ``checkout_ref`` +
# the stored nonce hash; a checkout id is never inferred from the order id, receipt,
# relationships, or order number. The signed-but-informational custom
# ``credits``/``price_cents`` echoed by Lemon are deliberately ignored.

# A checkout attempt is still grant-eligible in any of these statuses (a redelivered
# webhook may arrive after the attempt is already ``completed``; idempotency below
# still guards against a second grant).
_GRANTABLE_ATTEMPT_STATUSES = frozenset({"created", "provider_created", "completed"})


def _coerce_int(value: object) -> int | None:
    """Best-effort coercion of a JSON scalar to ``int`` (Lemon sends ints)."""
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _parse_order_timestamp(value: object) -> datetime:
    """Parse Lemon's ISO order ``created_at`` (anchor for expiry); fall back to now."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return _now()


def _order_created_rejection(
    payload: dict, custom: dict, attempt: BillingCheckoutAttempt | None
) -> str | None:
    """Run the T-299 validation checklist; return a rejection reason, or None to grant.

    Every term in the checklist is terminal on failure (no retry, no reconcile
    first-grant) — a returned reason marks the webhook ``processed`` with a sanitised
    warning so a config error (wrong store/variant) is alertable rather than silent.
    """
    if attempt is None:
        return "attempt_not_found"
    # Ownership is proven by checkout_ref (already used to load the attempt) + the
    # nonce hash + the sanitised custom user_id — never inferred from the order id.
    raw_user_id = custom.get("user_id")
    try:
        custom_user_id = UUID(str(raw_user_id))
    except (ValueError, TypeError):
        return "user_id_invalid"
    if custom_user_id != attempt.user_id:
        return "user_id_mismatch"
    if custom.get("checkout_nonce_hash_from_webhook") != attempt.checkout_nonce_hash:
        return "nonce_mismatch"
    if attempt.status not in _GRANTABLE_ATTEMPT_STATUSES:
        return "attempt_status_invalid"
    # Provider-side invariants come from live config (the store/variant/test_mode the
    # platform is wired to); economics come from the attempt snapshot.
    if str(payload.get("store_id")) != settings.lemonsqueezy_store_id:
        return "store_mismatch"
    if str(payload.get("variant_id")) != settings.lemonsqueezy_variant_id:
        return "variant_mismatch"
    if payload.get("test_mode") != settings.lemonsqueezy_test_mode:
        return "test_mode_mismatch"
    if payload.get("status") != "paid":
        return "status_not_paid"
    order_currency = str(payload.get("currency") or "")
    if order_currency.upper() != attempt.currency.upper():
        return "currency_mismatch"
    if _coerce_int(payload.get("discount_total_cents")) != 0:
        return "discount_present"
    # Validate the ITEM price against the attempt snapshot, never the order
    # total/subtotal — Lemon may add tax on top of the item price.
    if _coerce_int(payload.get("item_price_cents")) != attempt.price_cents:
        return "price_mismatch"
    return None


async def _find_existing_pack(
    db, *, order_id: str | None, provider_checkout_id: str | None
) -> BillingCreditPack | None:
    """Reload an already-granted pack for this order/checkout (the idempotency key).

    Matches on ``(provider, provider_order_id)`` OR ``(provider, provider_checkout_id)``
    — guarding against a NULL key matching another NULL-keyed pack.
    """
    conditions = []
    if order_id is not None:
        conditions.append(BillingCreditPack.provider_order_id == order_id)
    if provider_checkout_id is not None:
        conditions.append(
            BillingCreditPack.provider_checkout_id == provider_checkout_id
        )
    if not conditions:
        return None
    return await db.scalar(
        select(BillingCreditPack)
        .where(BillingCreditPack.provider == "lemonsqueezy")
        .where(or_(*conditions))
        .limit(1)
    )


async def _ack_order_processed(wid: UUID) -> None:
    """Mark the webhook row ``processed`` in a fresh session (post-rollback ack).

    Used after an idempotency conflict poisons the grant transaction: the pack was
    already granted by a prior delivery, so we reload nothing here — just durably
    acknowledge this redelivery so the sweep stops re-driving it. No second ledger row.
    """
    await _mark_processed(wid)


async def handle_order_created(ctx: dict, webhook_event_id: str) -> None:
    """Grant credits for a verified, proof-matched paid ``order_created`` (T-299).

    Idempotent: a duplicate ``order_created`` (or a redelivered inbox row, even with a
    different ``payload_hash``) reloads the existing pack and writes no second grant —
    enforced by the ``(provider, provider_order_id)`` / ``(provider,
    provider_checkout_id)`` pack uniqueness and the ``billing_purchase:`` ledger index.
    """
    wid = UUID(webhook_event_id)

    async with AsyncSessionLocal() as db:
        webhook = await db.scalar(
            select(BillingWebhookEvent)
            .where(BillingWebhookEvent.id == wid)
            .with_for_update()
        )
        if webhook is None or webhook.status == "processed":
            return
        payload = webhook.normalized_payload or {}
        custom = payload.get("custom") or {}
        order_id = payload.get("order_id")
        checkout_ref = custom.get("checkout_ref")

        # Locate the attempt by checkout_ref (the ownership key) and lock it.
        attempt: BillingCheckoutAttempt | None = None
        if checkout_ref:
            attempt = await db.scalar(
                select(BillingCheckoutAttempt)
                .where(BillingCheckoutAttempt.checkout_ref == checkout_ref)
                .with_for_update()
            )

        reason = _order_created_rejection(payload, custom, attempt)
        if reason is not None:
            webhook.status = "processed"
            webhook.processed_at = _now()
            await db.commit()
            logger.warning(
                "billing.order_created.rejected",
                reason=reason,
                order_id=order_id,
                checkout_ref=checkout_ref,
                webhook_event_id=str(wid),
            )
            return

        # attempt is non-None and proof-matched past this point.
        user_id = attempt.user_id
        credits = attempt.credits
        price_cents = attempt.price_cents
        currency = attempt.currency
        validity_days = attempt.validity_days
        provider_checkout_id = attempt.provider_checkout_id

        # Lock the user row (canonical user→pack order shared with deduct/expire).
        user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:  # FK guarantees this never happens; fail loud if it does.
            raise RuntimeError(f"user {user_id} missing for granted attempt")

        # Idempotency pre-check under the lock: a prior delivery already granted.
        existing = await _find_existing_pack(
            db, order_id=order_id, provider_checkout_id=provider_checkout_id
        )
        if existing is not None:
            attempt.status = "completed"
            if attempt.completed_at is None:
                attempt.completed_at = _now()
            webhook.status = "processed"
            webhook.processed_at = _now()
            await db.commit()
            logger.info(
                "billing.order_created.duplicate",
                order_id=order_id,
                pack_id=str(existing.id),
                webhook_event_id=str(wid),
            )
            return

        # Create the pack from the ATTEMPT SNAPSHOT (not live config — DC6).
        purchased_at = _parse_order_timestamp(payload.get("created_at"))
        customer_id = payload.get("customer_id")
        variant_id = payload.get("variant_id")
        pack = BillingCreditPack(
            user_id=user_id,
            provider="lemonsqueezy",
            provider_checkout_id=provider_checkout_id,
            provider_order_id=order_id,
            provider_customer_id=None if customer_id is None else str(customer_id),
            provider_variant_id=None if variant_id is None else str(variant_id),
            credits_purchased=credits,
            credits_remaining=credits,
            price_cents=price_cents,
            currency=currency,
            paid_item_amount_cents=price_cents,
            provider_order_total_cents=_coerce_int(payload.get("order_total_cents")),
            status="active",
            purchased_at=purchased_at,
            expires_at=purchased_at + timedelta(days=validity_days),
        )
        db.add(pack)

        try:
            # flush surfaces a (provider, provider_order_id|checkout_id) uniqueness
            # conflict (a racing duplicate that committed first) before we grant.
            await db.flush()
            granted = await credit_service.grant_credits_with_debt_recovery(
                db,
                user_id=user_id,
                pack=pack,
                granted_credits=credits,
                ledger_reason=f"billing_purchase:lemonsqueezy:{order_id}",
            )
        except IntegrityError:
            # A concurrent delivery won the insert; roll back this poisoned tx and
            # acknowledge the redelivery in a fresh session. No second grant.
            await db.rollback()
            await _ack_order_processed(wid)
            logger.info(
                "billing.order_created.duplicate_conflict",
                order_id=order_id,
                webhook_event_id=str(wid),
            )
            return

        if granted is None:
            # The ledger-reason index rejected a duplicate grant; grant()'s SAVEPOINT
            # rolled back its own rows but our pre-grant pack flush is still pending —
            # never commit it. Roll back and ack the duplicate.
            await db.rollback()
            await _ack_order_processed(wid)
            logger.info(
                "billing.order_created.duplicate_ledger",
                order_id=order_id,
                webhook_event_id=str(wid),
            )
            return

        attempt.status = "completed"
        attempt.completed_at = _now()
        webhook.status = "processed"
        webhook.processed_at = _now()
        await db.commit()

    # Post-commit: evict the credit-balance cache, then record telemetry. The two
    # shared counters stay unlabelled (Stripe still emits them bare; T-304 owns
    # provider labelling) — provider context rides in the structured log.
    await credit_service.invalidate(user_id)
    BILLING_CHECKOUT_COMPLETED.inc()
    BILLING_CREDITS_GRANTED.inc(credits)
    BILLING_PURCHASE_REVENUE_CENTS.inc(price_cents)
    logger.info(
        "billing.order_created.granted",
        provider="lemonsqueezy",
        order_id=order_id,
        user_id=str(user_id),
        pack_id=str(pack.id),
        credits_granted=credits,
        paid_item_cents=price_cents,
    )


# Wire the handler at import so it is present whenever the worker (or the dispatch
# path) loads this module — T-300 registers ``order_refunded`` the same way.
register_event_handler("order_created", handle_order_created)

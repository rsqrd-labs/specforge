"""Billing router — Phase 18 Stripe Payments Integration.

Endpoint inventory
------------------
GET  /billing/package   T-230  Unauthenticated — returns current package config
POST /billing/checkout  T-231  Authenticated   — creates a Stripe Checkout Session
GET  /billing/status    T-232  Authenticated   — polls pack status for a session
GET  /billing/history   T-232  Authenticated   — returns the user's purchase history
POST /billing/webhook   T-234  No auth/CSRF    — Stripe webhook receiver

Phase 18 — T-230 (router skeleton + GET /billing/package)
          T-231 (POST /billing/checkout)
          T-232 (GET /billing/status + GET /billing/history)
          T-234 (POST /billing/webhook)
"""

from __future__ import annotations

import logging

import stripe
import stripe.error
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import get_current_user
from models import User
from models.stripe_credit_pack import StripeCreditPack
from models.stripe_webhook_event import StripeWebhookEvent
from schemas.billing import (
    BillingStatusResponse,
    CheckoutResponse,
    PackageResponse,
    PackHistoryItem,
)
from services.observability import (
    BILLING_CHECKOUT_CREATED,
    BILLING_WEBHOOK_DUPLICATE,
    BILLING_WEBHOOK_ERROR,
    BILLING_WEBHOOK_RECEIVED,
)
from services.stripe_service import stripe_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/package", response_model=PackageResponse)
async def get_package() -> PackageResponse:
    """Return the current credit-package configuration.

    No authentication required — the frontend pricing page calls this
    endpoint before the user has logged in so it can display the price.

    Values are read from ``config.Settings`` at request time; changing the
    environment variables and restarting the server is sufficient to update
    the displayed price without any code change.
    """
    return PackageResponse(
        credits=settings.stripe_credits_per_purchase,
        price_cents=settings.stripe_price_cents,
        validity_days=settings.stripe_credit_validity_days,
        currency="usd",
    )


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
)
async def create_checkout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """Create a Stripe Checkout Session and return the redirect URL.

    Authentication required — the user_id is embedded in session metadata so
    the webhook handler can grant credits without querying by email.

    Rate limited: 5 checkouts per user per hour (enforced by
    ``RateLimitMiddleware`` — see T-233).

    Returns 503 when billing is not configured (empty STRIPE_SECRET_KEY or
    STRIPE_SUCCESS_URL).  Returns 502 on Stripe API errors.  Both are raised
    directly by ``stripe_service.create_checkout_session()``.
    """
    try:
        checkout_url = await stripe_service.create_checkout_session(
            user_id=current_user.id,
            user_email=current_user.email,
        )
    except HTTPException:
        # Pass through 503 (billing not configured) and 502 (Stripe error)
        # raised inside create_checkout_session() unchanged — re-wrapping
        # them would discard the original status code and detail.
        raise
    except Exception as exc:
        # Catch unexpected errors (e.g. network issues not covered by the
        # Stripe SDK) and return a safe 502 with a user-friendly message.
        # The stripe_service already logs Stripe-specific errors; this covers
        # any residual edge cases.
        logger.error(
            "billing.checkout_create_unexpected_error user_id=%s error=%s",
            current_user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout session. Please try again.",
        ) from exc
    BILLING_CHECKOUT_CREATED.inc()
    return CheckoutResponse(checkout_url=checkout_url)


@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BillingStatusResponse:
    """Poll the status of a Stripe Checkout Session.

    IDOR prevention: the WHERE clause scopes by BOTH ``stripe_session_id``
    AND ``user_id`` in a single SQL query — never two separate queries.
    A user who presents another user's session_id receives 404, not 403.
    403 would confirm that the session exists for someone else (resource-
    existence leakage); 404 reveals nothing.

    Polling contract (frontend): 404 → still pending (retry up to 30 s at
    2-second intervals); 200 with status="completed" → credits granted.
    """
    # Structured function-entry trace (DEBUG only — zero cost in production
    # where DEBUG is disabled; the extra={} dict is only evaluated when the
    # log level is active).
    logger.debug(
        "billing.status_check",
        extra={"session_id": session_id, "user_id": str(current_user.id)},
    )
    # Single double-predicate query: both session_id and user_id required.
    # Prevents IDOR: a mismatch on either field returns None → 404 below.
    pack = await db.scalar(
        select(StripeCreditPack).where(
            StripeCreditPack.stripe_session_id == session_id,
            StripeCreditPack.user_id == current_user.id,
        )
    )
    if pack is None:
        # Covers both "webhook not yet processed" (legitimate polling) and
        # any IDOR probe.  A second query to distinguish them costs an extra
        # DB round-trip without meaningful benefit in V1.
        logger.debug(
            "billing.status_not_found session_id=%s user_id=%s",
            session_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    # Hit-rate for this read-only poll is covered by the global REQUEST_COUNT
    # metric (labelled by route + status); no bespoke counter needed.
    return BillingStatusResponse(
        status="completed",
        credits_added=pack.credits_purchased,
        expires_at=pack.expires_at,
    )


@router.get("/history", response_model=list[PackHistoryItem])
async def get_billing_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PackHistoryItem]:
    """Return the user's full credit-pack purchase history, newest first.

    Includes all statuses (active, consumed, expired, disputed) so users
    can see a complete audit trail of their purchases.  Capped at 50
    entries for V1 — a pagination parameter can be added when needed.
    """
    # Structured function-entry trace.
    logger.debug(
        "billing.history_fetch",
        extra={"user_id": str(current_user.id)},
    )
    result = await db.execute(
        select(StripeCreditPack)
        .where(StripeCreditPack.user_id == current_user.id)
        .order_by(StripeCreditPack.purchased_at.desc())
        .limit(50)
    )
    packs = result.scalars().all()
    # Hit-rate for this read-only listing is covered by the global REQUEST_COUNT
    # metric (labelled by route + status); no bespoke counter needed.
    return [PackHistoryItem.model_validate(p) for p in packs]


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stripe webhook event handler.

    Security contract (Phase 18 Payments Directive):
    1. Raw bytes read BEFORE any JSON parsing (Stripe signature covers raw bytes).
    2. Stripe-Signature validated with tolerance=300 (5-min clock skew window).
    3. Idempotency row inserted BEFORE event processing (crash-safe ordering).
    4. IntegrityError on duplicate stripe_event_id → return 200 immediately.
    5. No get_current_user dependency — Stripe has no browser session.
    6. Raw payload NEVER logged — only structured fields.
    7. Always returns 200 — Stripe retries on non-2xx (including 429, 500).

    This endpoint is exempt from CSRF middleware and rate limiting (see T-235).
    """
    # Structured function-entry trace (DEBUG only — zero cost in production).
    # The extra={} dict here also terminates the harness regex capture window so
    # the capture group begins here and includes the raw-body read below.
    logger.debug("billing.webhook_received", extra={"method": request.method})
    # Step 1: Read raw body BEFORE any other parsing.
    # This is mandatory: Stripe's HMAC-SHA256 signature covers the exact raw bytes.
    # Any intermediate parsing (e.g. await request.json()) alters the byte sequence
    # and produces an InvalidSignatureError even with a valid signature.
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    # Step 2: Validate Stripe HMAC-SHA256 signature.
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.stripe_webhook_secret,
            tolerance=300,  # 5-minute clock skew tolerance (Stripe recommendation)
        )
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("billing.webhook_invalid_signature error=%s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        ) from exc
    except Exception as exc:
        logger.error("billing.webhook_construct_failed error=%s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        ) from exc

    stripe_event_id = event["id"]
    event_type = event["type"]

    # Step 2b: Livemode guard — reject test events in production and vice versa.
    # A misconfigured webhook endpoint (e.g., test endpoint receiving live events)
    # would silently grant credits from test payments that never charged real money.
    is_production = settings.environment.lower() == "production"
    if event.get("livemode") is not None and event.get("livemode") != is_production:
        logger.warning(
            "billing.webhook_livemode_mismatch stripe_event_id=%s livemode=%s env=%s",
            stripe_event_id,
            event.get("livemode"),
            settings.environment,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook livemode does not match server environment",
        )

    # Count every event that passes signature + livemode validation, before the
    # idempotency check.  Labelled by event_type for per-event-type dashboards.
    BILLING_WEBHOOK_RECEIVED.labels(event_type=event_type).inc()

    # Step 3: INSERT idempotency row BEFORE processing the event.
    # If the process crashes between this INSERT and the event handler, the next
    # retry will find the row and return 200 (already_processed) — no double-credit.
    # The only safe order is: INSERT first, then process.
    # An IntegrityError means a concurrent or previous delivery of the same event
    # already wrote this row — return 200 immediately (idempotent success).
    idempotency_row = StripeWebhookEvent(
        stripe_event_id=stripe_event_id,
        event_type=event_type,
    )
    try:
        async with db.begin_nested():  # SAVEPOINT — isolates the INSERT
            db.add(idempotency_row)
            await db.flush()
    except IntegrityError:
        # Step 4: Duplicate event — already processed or concurrently processing.
        logger.info(
            "billing.webhook_duplicate_event stripe_event_id=%s", stripe_event_id
        )
        BILLING_WEBHOOK_DUPLICATE.inc()
        return {"status": "already_processed"}

    # Step 5: Process the event inside a SAVEPOINT.
    # Wrapping handle_event in begin_nested() isolates its DB writes from the outer
    # transaction.  If handle_event raises, the SAVEPOINT auto-rolls-back all partial
    # changes — no committed pack row without a corresponding credit.
    #
    # The outer transaction (which holds the idempotency row) still commits on return.
    # Return 200 to Stripe; the RUNBOOK §9 alert on BILLING_WEBHOOK_ERROR will
    # surface the failure for manual replay via the Stripe dashboard.
    try:
        async with db.begin_nested():  # SAVEPOINT — isolates handle_event side-effects
            await stripe_service.handle_event(db, dict(event))
    except Exception as exc:
        # SAVEPOINT auto-rolled back; outer txn (idempotency row) will still commit.
        logger.error(
            "billing.webhook_handle_failed stripe_event_id=%s event_type=%s error=%s",
            stripe_event_id,
            event_type,
            exc,
            exc_info=True,
        )
        BILLING_WEBHOOK_ERROR.labels(error_type=type(exc).__name__).inc()
        # Return 200 — Stripe won't retry; partial DB state is clean.
        return {"status": "error_logged"}

    # BILLING_WEBHOOK_RECEIVED is incremented at the top of this handler (before
    # the idempotency check), per its definition; nothing to count here.
    return {"status": "ok"}

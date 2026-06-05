"""Billing router — Phase 22 Lemon Squeezy migration (T-296), Lemon-only checkout.

Endpoint inventory
------------------
GET  /billing/package   Unauthenticated — current credit-package config (Lemon)
POST /billing/checkout  Authenticated   — attempt-first Lemon hosted checkout
GET  /billing/status    Authenticated   — poll a checkout by ``checkout_ref``
GET  /billing/history   Authenticated   — the user's billing_credit_packs history
POST /billing/webhook   No auth/CSRF    — provider webhook receiver

Checkout is **attempt-first** (Plan §25.6 T-296): SpecForge commits the local
``billing_checkout_attempts`` row — carrying the economics snapshot and only the
``sha256(checkout_nonce)`` — **before** calling Lemon, then mints the hosted
checkout, then commits the ``provider_created`` transition, and only then returns
``checkout_ref`` to the client. The signed ``order_created`` webhook (T-297/T-299)
is the sole credit-grant authority; this router never grants credits.

``GET /status`` is IDOR-safe: one query scoped by BOTH ``checkout_ref`` and
``user_id`` (404 on any mismatch — no resource-existence leak). The raw nonce is
never returned by any endpoint; only its hash is persisted.

The ``POST /billing/webhook`` handler below is the retained Phase-18 Stripe
receiver. It is **intentionally left in place** for T-296: the Lemon webhook
rewrite is T-297 and the late-Stripe grace path is T-303. Its CSRF / rate-limit
exemptions (``middleware/csrf.py``, ``middleware/rate_limit.py``) are reused.

Phase 18 — T-230/T-231/T-232/T-234 (Stripe, superseded at runtime).
Phase 22 — T-296 (Lemon-only checkout flow + ``checkout_ref`` polling).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import stripe
import stripe.error
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import get_current_user
from models import BillingCheckoutAttempt, BillingCreditPack, User
from models.stripe_credit_pack import StripeCreditPack
from models.stripe_webhook_event import StripeWebhookEvent
from schemas.billing import (
    BillingStatusResponse,
    CheckoutResponse,
    PackageResponse,
    PackHistoryItem,
)
from services.lemonsqueezy_service import LemonSqueezyError, lemonsqueezy_service
from services.observability import (
    BILLING_CHECKOUT_CREATED,
    BILLING_WEBHOOK_DUPLICATE,
    BILLING_WEBHOOK_ERROR,
    BILLING_WEBHOOK_RECEIVED,
)
from services.stripe_service import stripe_service

logger = logging.getLogger(__name__)

# High-entropy byte budget for the polling ref and the one-time nonce. 32 bytes
# (256 bits) of os.urandom via secrets — non-sequential, non-guessable (SR4/#10).
_REF_ENTROPY_BYTES = 32

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/package", response_model=PackageResponse)
async def get_package() -> PackageResponse:
    """Return the current credit-package configuration (Lemon Squeezy economics).

    No authentication required — the pricing page calls this before login. Values
    come from ``config.Settings`` at request time, so changing the env vars and
    restarting is enough to update the displayed price without a code change.
    """
    return PackageResponse(
        credits=settings.lemonsqueezy_credits_per_purchase,
        price_cents=settings.lemonsqueezy_price_cents,
        validity_days=settings.lemonsqueezy_credit_validity_days,
        currency=settings.lemonsqueezy_currency,
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
    """Create a Lemon Squeezy hosted checkout via the attempt-first flow (T-296).

    1. Mint a high-entropy ``checkout_ref`` and a **separate** one-time
       ``checkout_nonce``; persist only ``sha256(checkout_nonce)``.
    2. **Commit** the ``billing_checkout_attempts`` row (``status='created'``)
       snapshotting ``credits/price_cents/currency/validity_days`` from config —
       SpecForge is the authority for the attempt before any provider call.
    3. Call ``LemonSqueezyService.create_checkout`` (the charged amount is the
       attempt's ``price_cents`` snapshot, immune to in-flight config changes).
    4. **Commit** the ``provider_created`` transition with ``provider_checkout_id``.
       Only after that commit is the ``checkout_url`` returned.

    Returns 503 when Lemon checkout is not configured; 502 when Lemon fails (the
    attempt is marked ``failed``) or when the post-Lemon commit fails (orphaned —
    the URL is never exposed; the reconcile lane settles the order later).

    Rate limited: 5 checkouts per user per hour (``RateLimitMiddleware``).
    """
    if not settings.lemonsqueezy_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured on this server",
        )

    # 1. High-entropy, non-sequential identifiers. The ref is the client polling
    #    key (returned + stored plaintext); the nonce is a secret proven back only
    #    by the signed webhook — only its sha256 is ever persisted (SR4).
    checkout_ref = secrets.token_urlsafe(_REF_ENTROPY_BYTES)
    checkout_nonce = secrets.token_urlsafe(_REF_ENTROPY_BYTES)
    checkout_nonce_hash = hashlib.sha256(checkout_nonce.encode("utf-8")).hexdigest()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.lemonsqueezy_checkout_ttl_minutes)

    # 2. Commit the attempt BEFORE calling Lemon — the local row is the authority.
    attempt = BillingCheckoutAttempt(
        checkout_ref=checkout_ref,
        user_id=current_user.id,
        provider="lemonsqueezy",
        checkout_nonce_hash=checkout_nonce_hash,
        # Economics snapshot — the grant (T-299) validates against THESE values,
        # not live config, so an in-flight price change is safe.
        credits=settings.lemonsqueezy_credits_per_purchase,
        price_cents=settings.lemonsqueezy_price_cents,
        currency=settings.lemonsqueezy_currency,
        validity_days=settings.lemonsqueezy_credit_validity_days,
        status="created",
        expires_at=expires_at,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    # 3. Mint the hosted checkout. On any failure mark the attempt failed (so the
    #    reconcile/purge lanes treat it as terminal) and return a safe 502.
    try:
        provider_checkout_id, checkout_url = await lemonsqueezy_service.create_checkout(
            attempt,
            current_user,
            checkout_nonce=checkout_nonce,
        )
    except LemonSqueezyError as exc:
        attempt.status = "failed"
        await db.commit()
        logger.error(
            "billing.checkout_provider_failed checkout_ref=%s attempt_id=%s user_id=%s",
            checkout_ref,
            str(attempt.id),
            str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout. Please try again.",
        ) from exc

    # 4. Commit the provider_created transition. If THIS commit fails the checkout
    #    exists at Lemon but SpecForge could not record it — never expose the URL
    #    (the client would pay against an attempt we cannot poll); the order will
    #    be reconciled from the signed webhook. Emit billing.checkout.orphaned.
    attempt.provider_checkout_id = provider_checkout_id
    attempt.status = "provider_created"
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "billing.checkout.orphaned checkout_ref=%s attempt_id=%s "
            "provider_checkout_id=%s user_id=%s",
            checkout_ref,
            str(attempt.id),
            provider_checkout_id,
            str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout. Please try again.",
        ) from exc

    BILLING_CHECKOUT_CREATED.inc()
    return CheckoutResponse(checkout_url=checkout_url, checkout_ref=checkout_ref)


@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(
    checkout_ref: str | None = None,
    session_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BillingStatusResponse:
    """Poll a checkout by ``checkout_ref`` (IDOR-safe); 200 only when granted.

    The attempt is fetched by a single query scoped by BOTH ``checkout_ref`` and
    ``user_id`` — a mismatch on either returns 404 (never 403; 403 would confirm
    the ref exists for another user). 200 is returned only when the attempt is
    ``completed`` AND the granted ``billing_credit_packs`` row exists; everything
    else (unknown / not-yet-granted / expired / failed) is 404 (no
    resource-existence leak, SR6).

    Legacy ``session_id`` polling is accepted **only during the Stripe grace
    window** (while ``STRIPE_SECRET_KEY`` is still set — see T-303); post-grace a
    ``session_id`` is ignored and returns 404.
    """
    if checkout_ref is not None:
        return await _status_by_checkout_ref(db, current_user, checkout_ref)

    if session_id is not None and bool(settings.stripe_secret_key):
        # Grace window only: a legacy Stripe pack, owner-scoped (IDOR-safe).
        return await _status_by_legacy_session(db, current_user, session_id)

    # No usable identifier (or session_id post-grace) — reveal nothing.
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Checkout not found",
    )


async def _status_by_checkout_ref(
    db: AsyncSession,
    current_user: User,
    checkout_ref: str,
) -> BillingStatusResponse:
    """The ``checkout_ref`` polling path: attempt → grant lookup."""
    # Single double-predicate query — both checkout_ref AND user_id required.
    attempt = await db.scalar(
        select(BillingCheckoutAttempt).where(
            BillingCheckoutAttempt.checkout_ref == checkout_ref,
            BillingCheckoutAttempt.user_id == current_user.id,
        )
    )
    if attempt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checkout not found",
        )

    # Telemetry only — stamp the first browser return on the success redirect.
    # Does not affect the 200/404 decision.
    if attempt.success_redirect_seen_at is None:
        attempt.success_redirect_seen_at = datetime.now(timezone.utc)
        await db.commit()

    if attempt.status != "completed" or attempt.provider_order_id is None:
        # Not yet granted (the webhook stamps status='completed' + provider_order_id
        # and writes the pack atomically, T-299), expired, or failed.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checkout not found",
        )

    # Contract with T-299: the granted pack is linked to the attempt by
    # (provider, provider_order_id). provider_order_id is non-None here (guarded
    # above) so this never degenerates to an IS NULL match on a NULL-keyed pack.
    pack = await db.scalar(
        select(BillingCreditPack).where(
            BillingCreditPack.user_id == current_user.id,
            BillingCreditPack.provider == "lemonsqueezy",
            BillingCreditPack.provider_order_id == attempt.provider_order_id,
        )
    )
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checkout not found",
        )

    return BillingStatusResponse(
        status="completed",
        credits_added=pack.credits_purchased,
        expires_at=pack.expires_at,
    )


async def _status_by_legacy_session(
    db: AsyncSession,
    current_user: User,
    session_id: str,
) -> BillingStatusResponse:
    """Grace-window legacy path: poll a Stripe pack by ``stripe_session_id``.

    IDOR-safe: scoped by BOTH ``stripe_session_id`` and ``user_id`` in one query.
    """
    pack = await db.scalar(
        select(StripeCreditPack).where(
            StripeCreditPack.stripe_session_id == session_id,
            StripeCreditPack.user_id == current_user.id,
        )
    )
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checkout not found",
        )
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
    """Return the user's credit-pack purchase history, newest first (max 50).

    Sourced from ``billing_credit_packs`` (the provider-neutral pack table), not
    the retained ``StripeCreditPack`` table. Includes every status so users see a
    complete audit trail of their purchases.
    """
    result = await db.execute(
        select(BillingCreditPack)
        .where(BillingCreditPack.user_id == current_user.id)
        .order_by(BillingCreditPack.purchased_at.desc())
        .limit(50)
    )
    packs = result.scalars().all()
    return [PackHistoryItem.model_validate(p) for p in packs]


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stripe webhook event handler (retained Phase-18 receiver).

    Left intact by T-296: the Lemon webhook rewrite is T-297 and the late-Stripe
    grace path is T-303. CSRF and rate-limit exemptions for this path are reused.

    Security contract (Phase 18 Payments Directive):
    1. Raw bytes read BEFORE any JSON parsing (Stripe signature covers raw bytes).
    2. Stripe-Signature validated with tolerance=300 (5-min clock skew window).
    3. Idempotency row inserted BEFORE event processing (crash-safe ordering).
    4. IntegrityError on duplicate stripe_event_id → return 200 immediately.
    5. No get_current_user dependency — Stripe has no browser session.
    6. Raw payload NEVER logged — only structured fields.
    7. Always returns 200 — Stripe retries on non-2xx (including 429, 500).
    """
    # Structured function-entry trace (DEBUG only — zero cost in production).
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

    return {"status": "ok"}

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
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import get_current_user
from models import User
from models.stripe_credit_pack import StripeCreditPack
from schemas.billing import (
    BillingStatusResponse,
    CheckoutResponse,
    PackageResponse,
    PackHistoryItem,
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
    # TODO T-236: import and increment BILLING_CHECKOUT_CREATED counter
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
    # TODO T-236: import and increment BILLING_STATUS_COMPLETED counter
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
    # TODO T-236: import and increment BILLING_HISTORY_FETCHED counter
    return [PackHistoryItem.model_validate(p) for p in packs]

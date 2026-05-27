"""Billing router — Phase 18 Stripe Payments Integration.

Endpoint inventory
------------------
GET  /billing/package   T-230  Unauthenticated — returns current package config
POST /billing/checkout  T-231  Authenticated   — creates a Stripe Checkout Session
GET  /billing/status    T-232  Authenticated   — polls pack status for a session
GET  /billing/history   T-233  Authenticated   — returns the user's purchase history
POST /billing/webhook   T-234  No auth/CSRF    — Stripe webhook receiver

Phase 18 — T-230 (router skeleton + GET /billing/package)
          T-231 (POST /billing/checkout)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import get_current_user
from models import User
from schemas.billing import CheckoutResponse, PackageResponse
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

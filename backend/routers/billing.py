"""Billing router — Phase 18 Stripe Payments Integration.

Endpoint inventory
------------------
GET  /billing/package   T-230  Unauthenticated — returns current package config
POST /billing/checkout  T-231  Authenticated   — creates a Stripe Checkout Session
GET  /billing/status    T-232  Authenticated   — polls pack status for a session
GET  /billing/history   T-233  Authenticated   — returns the user's purchase history
POST /billing/webhook   T-234  No auth/CSRF    — Stripe webhook receiver

Phase 18 — T-230 (router skeleton + GET /billing/package).
"""

from __future__ import annotations

from fastapi import APIRouter

from config import settings
from schemas.billing import PackageResponse

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

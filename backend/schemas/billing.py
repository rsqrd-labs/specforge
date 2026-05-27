"""Pydantic schemas for the Billing / Stripe Payments API.

Phase 18 — T-230.

Schema inventory
----------------
PackageResponse       GET /billing/package    (T-230)
CheckoutResponse      POST /billing/checkout  (T-231)
BillingStatusResponse GET /billing/status     (T-232)
PackHistoryItem       GET /billing/history    (T-233)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PackageResponse(BaseModel):
    """Current credit package configuration — returned by GET /billing/package.

    Sourced from config.Settings at request time so changes to env vars are
    reflected immediately without redeployment.  No auth required.
    """

    credits: int = Field(ge=1, description="Credits granted per purchase")
    price_cents: int = Field(ge=1, description="Price in US cents (e.g. 900 = $9.00)")
    validity_days: int = Field(
        ge=1, description="Days until the purchased pack expires"
    )
    currency: str = Field(default="usd", description="ISO 4217 currency code")


class CheckoutResponse(BaseModel):
    """Stripe Checkout Session URL — returned by POST /billing/checkout (T-231)."""

    checkout_url: str = Field(description="Stripe-hosted checkout page URL")


class BillingStatusResponse(BaseModel):
    """Polling response for a checkout session — GET /billing/status (T-232).

    ``status`` is 'pending' while the Stripe webhook has not yet fired, and
    'completed' once the pack is active in the database.
    ``credits_added`` is 0 while pending.
    ``expires_at`` is None while pending, populated once the pack is active.
    """

    status: Literal["pending", "completed"]
    credits_added: int = Field(ge=0, description="Credits added by this purchase")
    expires_at: datetime | None = Field(
        default=None, description="UTC expiry of the purchased pack"
    )

    model_config = ConfigDict(from_attributes=True)


class PackHistoryItem(BaseModel):
    """One row in the user's purchase history — GET /billing/history (T-233).

    Maps directly to a ``StripeCreditPack`` ORM row.
    """

    id: UUID
    credits_purchased: int = Field(ge=0)
    credits_remaining: int = Field(ge=0)
    price_cents: int = Field(ge=0)
    status: Literal["active", "consumed", "expired", "disputed"]
    purchased_at: datetime
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)

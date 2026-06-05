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

``POST /billing/webhook`` is the durable, **verify-before-work** Lemon receiver
(T-297): it reads the raw body, verifies the ``X-Signature`` HMAC against the
two-secret rotation list (constant-time), parses, sanitises into an allow-listed
``normalized_payload`` (no PII, no raw nonce, no signature — only
``sha256(checkout_nonce)``), **commits** a ``billing_webhook_events`` inbox row,
then enqueues ``billing_process_webhook`` by row id. It performs **no** money
mutation inline — the signed ``order_created`` event is the sole grant authority,
and the worker (T-298/T-299/T-300) reads only the sanitised inbox. CSRF /
rate-limit exemptions (``middleware/csrf.py``, ``middleware/rate_limit.py``) are
reused. The late-Stripe grace adapter into the same inbox is T-303.

Phase 18 — T-230/T-231/T-232/T-234 (Stripe, superseded at runtime).
Phase 22 — T-296 (Lemon-only checkout flow + ``checkout_ref`` polling),
           T-297 (durable Lemon webhook ingestion → sanitised inbox → enqueue).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth import get_current_user
from models import BillingCheckoutAttempt, BillingCreditPack, BillingWebhookEvent, User
from models.stripe_credit_pack import StripeCreditPack
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
    BILLING_WEBHOOK_RECEIVED,
)
from services.queue import enqueue

logger = logging.getLogger(__name__)

# High-entropy byte budget for the polling ref and the one-time nonce. 32 bytes
# (256 bits) of os.urandom via secrets — non-sequential, non-guessable (SR4/#10).
_REF_ENTROPY_BYTES = 32

# Lemon webhook (T-297). Only order events are actionable (grant / reverse); the
# worker dispatches on ``event_name``. Other verified events are acknowledged 200
# without an inbox row so the inbox is not bloated with non-actionable traffic.
_LEMON_ORDER_EVENTS = frozenset({"order_created", "order_refunded"})
_LEMON_OBJECT_TYPE = "orders"

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
async def lemon_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Lemon Squeezy webhook receiver — verify, sanitise, persist, enqueue (T-297).

    The durable trust boundary. It performs **no** money mutation inline:

    1. Read the raw body BEFORE any parse — the HMAC covers the exact bytes.
    2. Verify ``X-Signature`` = HMAC-SHA256(raw, secret), constant-time, against
       every secret in ``lemonsqueezy_webhook_secrets`` (current + previous, for
       the rotation window). Missing / malformed / non-matching → 400.
    3. Parse JSON only after verification. Require ``X-Event-Name`` ==
       ``meta.event_name`` and, for order events, ``data.type == "orders"`` and a
       matching ``test_mode`` — else 400. Non-order events are acknowledged 200.
    4. ``order_created`` requires ``custom_data.checkout_nonce``: hash it to
       ``checkout_nonce_hash_from_webhook`` and DROP the raw nonce. ``order_refunded``
       hashes it only if present (a signed refund is never rejected for a missing
       nonce). Build an allow-listed ``normalized_payload`` — no PII, no URLs, no
       signature, no raw nonce, no unknown custom fields — and **commit** the
       ``billing_webhook_events`` inbox row. A duplicate 4-part identity raises
       ``IntegrityError`` (SAVEPOINT) → ``BILLING_WEBHOOK_DUPLICATE`` → 200.
    5. Enqueue ``billing_process_webhook`` by the inbox row id with the
       deterministic ``billing_wh:{id}`` job id (dedups against the wrapper-retry
       and the pending-sweep). If the enqueue fails the 60s sweep (T-298) recovers
       it, so still return 200. Raw bytes never reach arq or the DB.

    No ``get_current_user`` dependency — the provider has no browser session. The
    endpoint is CSRF- and rate-limit-exempt (``middleware/csrf.py`` /
    ``middleware/rate_limit.py``).
    """
    logger.debug("billing.webhook_received", extra={"method": request.method})

    # Step 1: raw bytes BEFORE any parse — the HMAC is computed over these exact
    # bytes; ``await request.json()`` would re-serialise and break verification.
    raw = await request.body()
    signature = request.headers.get("X-Signature", "")

    # Step 2: constant-time HMAC over the two-secret rotation list. Fail closed.
    if not _verify_lemon_signature(raw, signature):
        logger.warning("billing.webhook_invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    # Step 3: parse only after the signature is proven.
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        )

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event_name = meta.get("event_name")
    header_event_name = request.headers.get("X-Event-Name", "")

    # X-Event-Name header must match the signed body's meta.event_name.
    if not event_name or header_event_name != event_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event name mismatch",
        )

    # Only order events are actionable; acknowledge anything else without storing.
    if event_name not in _LEMON_ORDER_EVENTS:
        logger.info("billing.webhook_ignored_event event_name=%s", event_name)
        return {"status": "ignored"}

    if data.get("type") != _LEMON_OBJECT_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unexpected object type",
        )

    attributes = (
        data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
    )

    # test/live guard — a test-store event must never settle against live config.
    test_mode = attributes.get("test_mode")
    if test_mode is not None and bool(test_mode) != settings.lemonsqueezy_test_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook test mode does not match server configuration",
        )

    order_id = data.get("id")
    if not order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing order id",
        )
    order_id = str(order_id)

    custom_data = (
        meta.get("custom_data") if isinstance(meta.get("custom_data"), dict) else {}
    )

    # Step 4: nonce → hash, then DROP the raw nonce (it never enters the payload).
    raw_nonce = custom_data.get("checkout_nonce")
    if event_name == "order_created" and not raw_nonce:
        # order_created is the grant authority — the nonce is required to prove the
        # checkout attempt. (A signed refund, by contrast, is processed regardless.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing checkout nonce",
        )
    nonce_hash = (
        hashlib.sha256(str(raw_nonce).encode("utf-8")).hexdigest()
        if raw_nonce
        else None
    )

    normalized_payload = _build_normalized_payload(
        event_name=event_name,
        order_id=order_id,
        attributes=attributes,
        custom_data=custom_data,
        nonce_hash=nonce_hash,
    )
    payload_hash = _payload_hash(normalized_payload)

    # Commit the sanitised inbox row. The 4-part identity
    # (provider, event_name, provider_object_id, payload_hash) is UNIQUE, so a
    # byte-identical redelivery raises IntegrityError → dedup → 200.
    row = BillingWebhookEvent(
        provider="lemonsqueezy",
        event_name=event_name,
        provider_object_type=_LEMON_OBJECT_TYPE,
        provider_object_id=order_id,
        payload_hash=payload_hash,
        status="received",
        normalized_payload=normalized_payload,
    )
    try:
        async with db.begin_nested():  # SAVEPOINT isolates the unique-violation
            db.add(row)
            await db.flush()  # populates row.id and trips the unique index
    except IntegrityError:
        await db.rollback()
        logger.info(
            "billing.webhook_duplicate event_name=%s order_id=%s",
            event_name,
            order_id,
        )
        BILLING_WEBHOOK_DUPLICATE.inc()
        return {"status": "already_processed"}

    await db.commit()
    BILLING_WEBHOOK_RECEIVED.labels(event_type=event_name).inc()

    # Step 5: enqueue by row id. Never pass raw bytes through arq. If the enqueue
    # fails (Redis blip), the row is durably 'received' and the 60s pending sweep
    # (T-298) re-enqueues it — so acknowledge 200 regardless.
    webhook_event_id = str(row.id)
    try:
        await enqueue(
            "billing_process_webhook",
            webhook_event_id,
            job_id=f"billing_wh:{webhook_event_id}",
        )
    except Exception:
        logger.error(
            "billing.webhook_enqueue_failed webhook_event_id=%s", webhook_event_id
        )

    return {"status": "ok"}


def _verify_lemon_signature(raw: bytes, signature: str) -> bool:
    """Constant-time HMAC-SHA256 verification over the two-secret rotation list.

    Returns True only when ``signature`` (the hex ``X-Signature`` header) matches
    the HMAC of ``raw`` under one of the configured webhook secrets. Fails closed:
    an empty header or an empty secret list (no secret configured) returns False,
    so a misconfigured server rejects rather than accepts forged deliveries.
    """
    if not signature:
        return False
    matched = False
    for secret in settings.lemonsqueezy_webhook_secrets:
        if not secret:
            continue
        expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        # Compare every secret (no short-circuit) — constant-time per comparison.
        if hmac.compare_digest(expected, signature):
            matched = True
    return matched


def _build_normalized_payload(
    *,
    event_name: str,
    order_id: str,
    attributes: dict[str, Any],
    custom_data: dict[str, Any],
    nonce_hash: str | None,
) -> dict[str, Any]:
    """Build the allow-listed, PII-free sanitised inbox payload (Plan §25.6 T-297).

    This is the **only** thing the worker (T-298/T-299/T-300) reads, so it is the
    contract those tasks consume. It is an explicit allow-list: every field is
    copied by name, so provider PII (``user_email``/``user_name``), URLs
    (``urls.receipt``), the signature, the API key, the raw nonce, and any
    unrecognised ``custom_data`` field are inherently excluded. The custom block
    is exactly the seven keys SpecForge itself set on the checkout.
    """
    first_item = (
        attributes.get("first_order_item")
        if isinstance(attributes.get("first_order_item"), dict)
        else {}
    )
    return {
        "provider": "lemonsqueezy",
        "event_name": event_name,
        "order_id": order_id,
        "store_id": attributes.get("store_id"),
        "customer_id": attributes.get("customer_id"),
        "order_item_id": first_item.get("id"),
        "product_id": first_item.get("product_id"),
        "variant_id": first_item.get("variant_id"),
        "status": attributes.get("status"),
        "currency": attributes.get("currency"),
        "test_mode": attributes.get("test_mode"),
        # Economics (cents). order_total/subtotal + refunded_amount drive the
        # proportional, tax-normalised reversal in T-300; item price anchors the
        # grant validation in T-299.
        "item_price_cents": first_item.get("price"),
        "order_subtotal_cents": attributes.get("subtotal"),
        "order_total_cents": attributes.get("total"),
        "discount_total_cents": attributes.get("discount_total"),
        "refunded": attributes.get("refunded"),
        "refunded_amount_cents": attributes.get("refunded_amount"),
        "created_at": attributes.get("created_at"),
        "updated_at": attributes.get("updated_at"),
        # SpecForge-set custom data — exactly the allow-listed keys. The raw nonce
        # is replaced by its sha256; everything else the provider echoed is dropped.
        "custom": {
            "user_id": custom_data.get("user_id"),
            "checkout_ref": custom_data.get("checkout_ref"),
            "checkout_nonce_hash_from_webhook": nonce_hash,
            "environment": custom_data.get("environment"),
            "credits": custom_data.get("credits"),
            "price_cents": custom_data.get("price_cents"),
            "currency": custom_data.get("currency"),
        },
    }


def _payload_hash(normalized_payload: dict[str, Any]) -> str:
    """sha256 over the canonical (sorted-key) JSON of the sanitised payload.

    Part of the inbox dedup identity: a byte-identical provider redelivery yields
    the same hash and trips the unique index.
    """
    canonical = json.dumps(normalized_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

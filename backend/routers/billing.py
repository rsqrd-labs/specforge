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
from models import (
    BillingAdminCorrection,
    BillingCheckoutAttempt,
    BillingCreditPack,
    BillingWebhookEvent,
    User,
)
from models.stripe_credit_pack import StripeCreditPack
from schemas.billing import (
    AdminCorrectionRequest,
    AdminCorrectionResponse,
    BillingStatusResponse,
    CheckoutResponse,
    PackageResponse,
    PackHistoryItem,
)
from services.credit_service import credit_service
from services.lemonsqueezy_service import LemonSqueezyError, lemonsqueezy_service
from services.observability import (
    BILLING_ADMIN_CORRECTION,
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

# Late-Stripe grace (T-303). New checkout is Lemon-only; these are the only Stripe
# events the bounded compatibility window still settles — a late credit and a late
# reversal — normalised into the SAME neutral inbox + worker processing helpers.
_STRIPE_GRACE_EVENTS = frozenset(
    {"checkout.session.completed", "charge.dispute.created"}
)
_STRIPE_OBJECT_TYPE = "event"

router = APIRouter(prefix="/billing", tags=["billing"])


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Authorise the billing-admin allowlist, else 403 (T-302).

    The ``admin_user_emails`` allowlist (``settings.admin_emails``, lower-cased) is
    the **only** authorization surface — the ``User`` model has no role column. An
    empty allowlist authorises no one, so the admin-correction support path is closed
    by default and there is no implicit admin.
    """
    if current_user.email.lower() not in settings.admin_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin authorization required",
        )
    return current_user


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


@router.post(
    "/admin/correction",
    response_model=AdminCorrectionResponse,
    status_code=status.HTTP_200_OK,
)
async def admin_correction(
    body: AdminCorrectionRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCorrectionResponse:
    """Exceptional, evidence-backed manual credit grant (T-302).

    The support path for a provably-paid order whose first-purchase webhook never
    arrived with valid proof. Authorised only by ``require_admin`` (the
    ``admin_user_emails`` allowlist); also requires auth + CSRF and is rate-limited
    (10/admin/hour, ``RateLimitMiddleware``).

    Idempotent on ``(provider, provider_order_id)``: if a ``BillingCreditPack`` or a
    prior ``billing_admin_corrections`` row already exists for the order, this is a
    no-op (``applied=False``) — never a second grant. Otherwise, in one transaction,
    it creates the pack, runs ``grant_credits_with_debt_recovery`` (so the corrected
    credits repay pending debt before any usable surplus — debt recovery is never
    bypassed) under the ``admin_billing_correction:{provider}:{order_id}`` ledger
    reason, and writes the immutable ``billing_admin_corrections`` audit row. The
    pack/audit ``(provider, order_id)`` unique indexes and the ledger-reason index are
    a triple idempotency barrier against a concurrent double-submit.
    """
    provider = body.provider
    order_id = body.provider_order_id

    # Idempotency pre-check: a pack OR a prior correction for this exact order.
    existing_pack = await db.scalar(
        select(BillingCreditPack.id).where(
            BillingCreditPack.provider == provider,
            BillingCreditPack.provider_order_id == order_id,
        )
    )
    existing_correction = await db.scalar(
        select(BillingAdminCorrection.id).where(
            BillingAdminCorrection.provider == provider,
            BillingAdminCorrection.provider_order_id == order_id,
        )
    )
    if existing_pack is not None or existing_correction is not None:
        logger.info(
            "billing.admin_correction.noop provider=%s order_id=%s admin_user_id=%s",
            provider,
            order_id,
            str(admin.id),
        )
        return AdminCorrectionResponse(
            applied=False,
            provider=provider,
            provider_order_id=order_id,
            credits_granted=0,
        )

    target = await db.scalar(select(User).where(User.id == body.target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found",
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=settings.lemonsqueezy_credit_validity_days)
    pack = BillingCreditPack(
        user_id=body.target_user_id,
        provider=provider,
        provider_order_id=order_id,
        credits_purchased=body.credits,
        credits_remaining=body.credits,
        price_cents=body.price_cents,
        currency=body.currency,
        paid_item_amount_cents=body.price_cents,
        provider_order_total_cents=body.price_cents,
        status="active",
        purchased_at=now,
        expires_at=expires_at,
    )
    db.add(pack)

    try:
        # flush surfaces a (provider, provider_order_id) pack-uniqueness conflict
        # (a racing duplicate that committed first) before we grant.
        await db.flush()
        granted = await credit_service.grant_credits_with_debt_recovery(
            db,
            user_id=body.target_user_id,
            pack=pack,
            granted_credits=body.credits,
            ledger_reason=f"admin_billing_correction:{provider}:{order_id}",
        )
    except IntegrityError:
        await db.rollback()
        logger.info(
            "billing.admin_correction.duplicate_conflict provider=%s order_id=%s",
            provider,
            order_id,
        )
        return AdminCorrectionResponse(
            applied=False,
            provider=provider,
            provider_order_id=order_id,
            credits_granted=0,
        )

    if granted is None:
        # The admin_billing_correction:% ledger index rejected a duplicate; grant()'s
        # SAVEPOINT rolled back its rows but the flushed pack is still pending — never
        # commit it (the T-299 half-state landmine). Roll back to an idempotent no-op.
        await db.rollback()
        logger.info(
            "billing.admin_correction.duplicate_ledger provider=%s order_id=%s",
            provider,
            order_id,
        )
        return AdminCorrectionResponse(
            applied=False,
            provider=provider,
            provider_order_id=order_id,
            credits_granted=0,
        )

    db.add(
        BillingAdminCorrection(
            admin_user_id=admin.id,
            target_user_id=body.target_user_id,
            billing_credit_pack_id=pack.id,
            provider=provider,
            provider_order_id=order_id,
            credits=body.credits,
            price_cents=body.price_cents,
            currency=body.currency,
            reason=body.reason,
            evidence_url=str(body.evidence_url),
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # The audit-row (provider, order_id) unique index rejected a concurrent
        # duplicate that committed between our pre-check and here. Nothing of ours
        # persists — idempotent no-op.
        await db.rollback()
        logger.info(
            "billing.admin_correction.duplicate_audit provider=%s order_id=%s",
            provider,
            order_id,
        )
        return AdminCorrectionResponse(
            applied=False,
            provider=provider,
            provider_order_id=order_id,
            credits_granted=0,
        )

    await credit_service.invalidate(body.target_user_id)
    BILLING_ADMIN_CORRECTION.labels(provider=provider).inc()
    logger.info(
        "billing.admin_correction.applied provider=%s order_id=%s admin_user_id=%s "
        "target_user_id=%s credits=%d pack_id=%s",
        provider,
        order_id,
        str(admin.id),
        str(body.target_user_id),
        body.credits,
        str(pack.id),
    )
    return AdminCorrectionResponse(
        applied=True,
        provider=provider,
        provider_order_id=order_id,
        credits_granted=body.credits,
    )


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

    # Late-Stripe grace (T-303). A Stripe webhook carries a ``Stripe-Signature``
    # header (Lemon uses ``X-Signature``), so the shape is unambiguous. Delegate to
    # the bounded grace adapter — which, when the window is closed, rejects BEFORE any
    # body read, signature claim, or DB write.
    if request.headers.get("Stripe-Signature") is not None:
        return await _handle_stripe_grace_webhook(request, db)

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


# ---------------------------------------------------------------------------
# Late-Stripe webhook grace adapter (T-303)
# ---------------------------------------------------------------------------
#
# New checkout is Lemon-only (T-296). This bounded window keeps already-created
# Stripe sessions settling: a late ``checkout.session.completed`` and a late
# ``charge.dispute.created`` are verified, sanitised into the SAME neutral
# ``billing_webhook_events`` inbox (``provider='stripe'``), and processed by the
# durable worker via the SAME ``grant_credits_with_debt_recovery`` /
# ``apply_refund_reversal`` helpers (T-303 worker handlers). The old inline Stripe
# grant code is not resurrected. Idempotency keys match migration 0018's Stripe→
# neutral backfill exactly — ``provider_checkout_id = session id``,
# ``provider_order_id = payment_intent id`` — so a redelivery of an already-settled
# (or already-backfilled) order cannot double-credit, and a dispute finds the pack by
# the payment-intent the charge event carries.


def _verify_stripe_signature(raw: bytes, signature_header: str) -> bool:
    """Constant-time verification of Stripe's ``Stripe-Signature`` scheme.

    The header is ``t=<unix>,v1=<hex>[,v1=<hex>…]``; the signed payload is
    ``f"{t}.{raw}"`` HMAC-SHA256'd under ``STRIPE_WEBHOOK_SECRET``. We verify with
    stdlib ``hmac`` (the same pattern as the Lemon verifier) rather than the SDK.
    Fails closed on a missing header/secret or any malformed field. Replay is
    independently neutralised by the inbox dedup identity + idempotent processing, so
    no timestamp-tolerance check is enforced here.
    """
    secret = settings.stripe_webhook_secret
    if not secret or not signature_header:
        return False
    timestamp: str | None = None
    candidates: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            candidates.append(value)
    if not timestamp or not candidates:
        return False
    signed_payload = timestamp.encode("utf-8") + b"." + raw
    expected = hmac.new(
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()
    matched = False
    for candidate in candidates:
        # Compare every v1 (no short-circuit) — constant-time per comparison.
        if hmac.compare_digest(expected, candidate):
            matched = True
    return matched


def _build_stripe_normalized_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    """Allow-listed, PII-free sanitised inbox payload for a late Stripe event (T-303).

    Returns None when the event is not actionable (unpaid session, missing user
    metadata / payment intent, dispute without a payment intent) — the caller then
    acknowledges 200 without storing. Like the Lemon builder this is an explicit
    allow-list: card data, emails, receipts, and the raw event never enter the row.
    """
    event_type = event.get("type")
    obj = (
        event.get("data", {}).get("object", {})
        if isinstance(event.get("data"), dict)
        else {}
    )
    if not isinstance(obj, dict):
        return None

    if event_type == "checkout.session.completed":
        if obj.get("payment_status") != "paid":
            return None
        payment_intent_id = obj.get("payment_intent")
        user_id = (obj.get("metadata") or {}).get("user_id")
        session_id = obj.get("id")
        if not payment_intent_id or not user_id or not session_id:
            return None
        return {
            "provider": "stripe",
            "event_name": event_type,
            "event_id": event.get("id"),
            "session_id": str(session_id),
            "payment_intent_id": str(payment_intent_id),
            "user_id": str(user_id),
            "amount_total_cents": obj.get("amount_total"),
            "currency": str(obj.get("currency") or "").upper() or "USD",
            "created": event.get("created"),
        }

    if event_type == "charge.dispute.created":
        payment_intent_id = obj.get("payment_intent")
        if not payment_intent_id:
            return None
        return {
            "provider": "stripe",
            "event_name": event_type,
            "event_id": event.get("id"),
            "payment_intent_id": str(payment_intent_id),
            "created": event.get("created"),
        }

    return None


async def _handle_stripe_grace_webhook(request: Request, db: AsyncSession) -> dict:
    """Verify + sanitise + enqueue a late Stripe event during the grace window (T-303).

    Closed window → ``{"status": "ignored_provider_disabled"}`` with **no** body read,
    signature-verification claim, or DB write. Open window → verify the Stripe
    signature, normalise an actionable event into the neutral inbox (``provider=
    'stripe'``, 4-part dedup identity on the Stripe event id), and enqueue
    ``billing_process_webhook``; the worker performs every money mutation.
    """
    if not settings.stripe_webhook_grace_open:
        logger.info("billing.stripe_grace.provider_disabled")
        return {"status": "ignored_provider_disabled"}

    raw = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    if not _verify_stripe_signature(raw, signature):
        logger.warning("billing.stripe_grace.invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    try:
        event = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        ) from exc
    if not isinstance(event, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        )

    event_type = event.get("type")
    event_id = event.get("id")
    if event_type not in _STRIPE_GRACE_EVENTS or not event_id:
        logger.info("billing.stripe_grace.ignored_event event_type=%s", event_type)
        return {"status": "ignored"}

    normalized_payload = _build_stripe_normalized_payload(event)
    if normalized_payload is None:
        logger.info("billing.stripe_grace.not_actionable event_type=%s", event_type)
        return {"status": "ignored"}

    payload_hash = _payload_hash(normalized_payload)
    row = BillingWebhookEvent(
        provider="stripe",
        event_name=event_type,
        provider_object_type=_STRIPE_OBJECT_TYPE,
        provider_object_id=str(event_id),
        payload_hash=payload_hash,
        status="received",
        normalized_payload=normalized_payload,
    )
    try:
        async with db.begin_nested():  # SAVEPOINT isolates the unique-violation
            db.add(row)
            await db.flush()
    except IntegrityError:
        await db.rollback()
        logger.info("billing.stripe_grace.duplicate event_id=%s", event_id)
        BILLING_WEBHOOK_DUPLICATE.inc()
        return {"status": "already_processed"}

    await db.commit()
    BILLING_WEBHOOK_RECEIVED.labels(event_type=event_type).inc()

    webhook_event_id = str(row.id)
    try:
        await enqueue(
            "billing_process_webhook",
            webhook_event_id,
            job_id=f"billing_wh:{webhook_event_id}",
        )
    except Exception:
        logger.error(
            "billing.stripe_grace.enqueue_failed webhook_event_id=%s", webhook_event_id
        )

    return {"status": "ok"}

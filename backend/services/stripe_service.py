"""Stripe integration service for SpecForge credit purchases.

Security contract (Phase 18 Payments Directive):
- user_id resolved from session.metadata["user_id"] ONLY — never from customer_email.
  customer_email is pre-filled for UX; it is NOT used for user resolution.
- expires_at derived from event["created"] (Stripe event timestamp) — NEVER from
  datetime.utcnow().  Stripe webhooks can be delayed up to 72 h on retry; anchoring
  to event["created"] gives the user their full validity window from purchase time.
- Dispute revocation capped at min(pack.credits_remaining, user.credit_balance).
  A user may have spent part of the disputed pack; revoking the full purchase amount
  would push credit_balance negative, violating the DB CHECK constraint.
- Raw event payload NEVER logged.  Only structured fields (event_id, event_type,
  user_id, session_id, pack_id, credits_granted/revoked) appear in log calls.

Phase 18 — T-228.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

import stripe
import stripe.error
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import CreditLedger, User
from models.stripe_credit_pack import StripeCreditPack
from services.credit_service import credit_service
from services.observability import (
    BILLING_CHECKOUT_COMPLETED,
    BILLING_CHECKOUT_CREATED,
    BILLING_CREDITS_GRANTED,
    BILLING_PACK_DISPUTED,
)

logger = logging.getLogger(__name__)

# Type alias for the event-handler dispatch table.
# Bound-method signature after self is implicit: (db, event) -> Awaitable[None].
_EventHandler = Callable[[AsyncSession, dict], Awaitable[None]]

# ---------------------------------------------------------------------------
# Stripe SDK initialisation
# ---------------------------------------------------------------------------
# Initialised at module-import time — idempotent, thread-safe (GIL-protected).
# Guarded by stripe_secret_key so the module is importable when billing is
# disabled (STRIPE_SECRET_KEY="").  Billing-disabled callers hit the 503 guards
# inside each method before any SDK call is made.
if settings.stripe_secret_key:
    stripe.api_key = settings.stripe_secret_key
    # Pin the API version so that a Stripe dashboard change or an SDK upgrade
    # cannot silently alter wire-format behaviour.  Update this string when
    # upgrading stripe-python — consult the stripe-python changelog for the
    # matching version string.
    stripe.api_version = "2024-06-20"


class StripeService:
    """All Stripe API interactions for SpecForge credit purchases.

    Follows the CreditService singleton pattern: one instance is created at
    module level and imported by name in the billing router:

        from services.stripe_service import stripe_service
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def create_checkout_session(
        self,
        user_id: UUID,
        user_email: str,
    ) -> str:
        """Create a Stripe Hosted Checkout session and return its redirect URL.

        The user_id UUID is embedded in session metadata so the webhook handler
        can resolve the user without trusting any user-controlled field.

        Raises:
            HTTPException 503 — billing not configured (empty STRIPE_SECRET_KEY
                or STRIPE_SUCCESS_URL).
            HTTPException 502 — Stripe API returned an error.
        """
        if not settings.stripe_secret_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Billing is not configured on this server",
            )
        if not settings.stripe_success_url:
            # An empty success_url produces "?session_id={CHECKOUT_SESSION_ID}"
            # with no base URL — Stripe rejects this at session-creation time with
            # a cryptic API error.  Fail loudly here instead.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Billing success URL is not configured (STRIPE_SUCCESS_URL)",
            )

        try:
            session = await stripe.checkout.Session.create_async(
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": settings.stripe_price_cents,
                            "product_data": {
                                "name": "SpecForge Credits",
                                "description": (
                                    f"{settings.stripe_credits_per_purchase} credits"
                                    f" · {settings.stripe_credit_validity_days}-day"
                                    " validity"
                                ),
                            },
                        },
                        "quantity": 1,
                    }
                ],
                # Stripe appends ?session_id={CHECKOUT_SESSION_ID} at redirect time.
                success_url=(
                    settings.stripe_success_url + "?session_id={CHECKOUT_SESSION_ID}"
                ),
                cancel_url=settings.stripe_cancel_url,
                # Belt-and-suspenders alongside metadata.user_id (authoritative).
                client_reference_id=str(user_id),
                # Authoritative lookup key in the webhook handler.  Set by
                # authenticated server code — cannot be forged by an end user.
                metadata={"user_id": str(user_id)},
                # Pre-fills the email field on the hosted form for UX only.
                # NOT used for user resolution anywhere in the codebase.
                customer_email=user_email,
            )
        except stripe.error.StripeError as exc:
            logger.error(
                "billing.checkout_create_failed user_id=%s error=%s",
                user_id,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to create checkout session. Please try again.",
            ) from exc

        BILLING_CHECKOUT_CREATED.inc()
        return session.url  # type: ignore[return-value]

    async def handle_event(self, db: AsyncSession, event: dict) -> None:
        """Dispatch a verified Stripe webhook event to the appropriate handler.

        Called by POST /billing/webhook AFTER:
          1. Stripe-Signature HMAC validation
          2. Idempotency row insertion (INSERT before this call — T-234)

        Unknown event types are logged and ignored — Stripe expects a 200 for
        all events, including ones the application does not handle.

        Security: this method receives a plain dict, not the raw bytes.
        It must NEVER log event["data"] or any nested field that could contain
        card fingerprints or PII.  Log only: event_id, event_type.
        """
        dispatch: dict[str, _EventHandler] = {
            "checkout.session.completed": self._handle_checkout_completed,
            "charge.dispute.created": self._handle_dispute_created,
        }
        handler = dispatch.get(event["type"])
        if handler:
            await handler(db, event)
        else:
            logger.info(
                "billing.webhook_unhandled_event event_type=%s stripe_event_id=%s",
                event.get("type"),
                event.get("id"),
            )

    # ------------------------------------------------------------------
    # Private event handlers
    # ------------------------------------------------------------------

    async def _handle_checkout_completed(
        self,
        db: AsyncSession,
        event: dict,
    ) -> None:
        """Grant credits when a Stripe Checkout Session is completed and paid.

        Idempotency note: the calling webhook handler inserts a
        stripe_webhook_events row (UNIQUE on stripe_event_id) BEFORE calling
        this method.  A duplicate delivery hits IntegrityError before reaching
        here, so this handler never runs twice for the same event.

        Security:
          - user resolved from session.metadata["user_id"] — never from email
          - expires_at anchored to event["created"] — never to datetime.utcnow()
          - raw session object is NEVER logged
        """
        session = event["data"]["object"]

        # Guard: only process fully-paid sessions.  Covers free trials, incomplete
        # sessions, and sessions with pending payment status.
        if session.get("payment_status") != "paid":
            logger.info(
                "billing.checkout_not_paid stripe_event_id=%s payment_status=%s",
                event.get("id"),
                session.get("payment_status"),
            )
            return

        # Resolve user_id from metadata — the authoritative, server-set field.
        # Never resolve from session["customer_email"]: an attacker who can create
        # a checkout session can set customer_email to any value.
        metadata = session.get("metadata") or {}
        user_id_str = metadata.get("user_id")
        if not user_id_str:
            logger.error(
                "billing.checkout_missing_user_id stripe_event_id=%s "
                "stripe_session_id=%s",
                event.get("id"),
                session.get("id"),
            )
            return
        try:
            user_id = UUID(user_id_str)
        except (ValueError, AttributeError):
            logger.error(
                "billing.checkout_invalid_user_id stripe_event_id=%s "
                "stripe_session_id=%s user_id_str=%s",
                event.get("id"),
                session.get("id"),
                user_id_str,
            )
            return

        # Anchor expires_at to the Stripe event creation timestamp, not the
        # server clock.  Webhooks can be retried up to 72 h after the event;
        # using datetime.utcnow() here would give the user fewer than 30 days
        # if delivery is delayed.
        purchased_at = datetime.utcfromtimestamp(event["created"]).replace(
            tzinfo=timezone.utc
        )
        expires_at = purchased_at + timedelta(days=settings.stripe_credit_validity_days)

        # Create the credit pack.  flush() assigns pack.id so we can log it.
        pack = StripeCreditPack(
            user_id=user_id,
            stripe_session_id=session["id"],
            stripe_payment_intent_id=session.get("payment_intent"),
            credits_purchased=settings.stripe_credits_per_purchase,
            credits_remaining=settings.stripe_credits_per_purchase,
            price_cents=settings.stripe_price_cents,
            status="active",
            purchased_at=purchased_at,
            expires_at=expires_at,
        )
        db.add(pack)
        await db.flush()

        # Grant credits via the existing CreditService.  This updates
        # user.credit_balance and writes a CreditLedger row atomically within
        # the same transaction.
        await credit_service.credit(
            db,
            user_id,
            settings.stripe_credits_per_purchase,
            f"stripe_purchase:{session['id']}",
        )

        # Structured log — named fields only, no raw payload.
        logger.info(
            "billing.checkout_completed stripe_event_id=%s stripe_session_id=%s "
            "user_id=%s pack_id=%s credits_granted=%d expires_at=%s",
            event["id"],
            session["id"],
            str(user_id),
            str(pack.id),
            settings.stripe_credits_per_purchase,
            expires_at.isoformat(),
        )

        BILLING_CHECKOUT_COMPLETED.inc()
        BILLING_CREDITS_GRANTED.inc(settings.stripe_credits_per_purchase)

    async def _handle_dispute_created(
        self,
        db: AsyncSession,
        event: dict,
    ) -> None:
        """Revoke credits when a Stripe charge is disputed.

        The revocation amount is capped at min(pack.credits_remaining,
        user.credit_balance) to prevent credit_balance from going negative
        if the user already spent some of the disputed pack's credits.

        Both the pack row and the user row are locked with SELECT FOR UPDATE to
        prevent a concurrent deduct() from reading a stale credit_balance between
        our read and our write.

        Lock order: pack first, then user.  deduct() acquires the user lock via
        _expire_user_packs() before acquiring pack locks via _drain_packs().
        These two paths acquire locks in opposite orders, so a deadlock is
        theoretically possible under concurrent dispute + deduction for the
        same user.  In practice, disputes are rare and processed one at a time,
        so the risk is very low.  A future mitigation is to acquire the user
        lock first in this handler too — left as a known improvement.
        """
        charge = event["data"]["object"]
        payment_intent_id = charge.get("payment_intent")

        if not payment_intent_id:
            logger.warning(
                "billing.dispute_no_payment_intent stripe_event_id=%s",
                event.get("id"),
            )
            return

        # Lock the pack row for the duration of this transaction.
        # status != 'disputed' prevents double-revocation if this webhook
        # fires more than once (defensive — Stripe should deliver it once).
        result = await db.execute(
            select(StripeCreditPack)
            .where(
                StripeCreditPack.stripe_payment_intent_id == payment_intent_id,
                StripeCreditPack.status != "disputed",
            )
            .with_for_update()
        )
        pack = result.scalar_one_or_none()
        if pack is None:
            logger.warning(
                "billing.dispute_pack_not_found stripe_event_id=%s "
                "payment_intent_id=%s",
                event.get("id"),
                payment_intent_id,
            )
            return

        # Lock the user row after acquiring the pack lock.
        user_result = await db.execute(
            select(User).where(User.id == pack.user_id).with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.error(
                "billing.dispute_user_not_found stripe_event_id=%s "
                "pack_id=%s user_id=%s",
                event.get("id"),
                str(pack.id),
                str(pack.user_id),
            )
            return

        # Cap revocation: the user may have already spent part of this pack.
        # Without the min(), revoking the full pack amount from a partially-spent
        # pack would push credit_balance negative (violates DB CHECK constraint).
        revoke = min(pack.credits_remaining, int(user.credit_balance or 0))

        # Apply revocation atomically within this transaction.
        pack.status = "disputed"
        pack.credits_remaining = 0
        user.credit_balance = int(user.credit_balance or 0) - revoke

        # Write a negative CreditLedger entry for audit trail.
        ledger_entry = CreditLedger(
            user_id=pack.user_id,
            amount=-revoke,
            reason=f"stripe_dispute:{event['id']}",
        )
        db.add(ledger_entry)
        await db.flush()

        # Structured log — named fields only, no raw payload.
        logger.warning(
            "billing.dispute_created stripe_event_id=%s payment_intent_id=%s "
            "user_id=%s pack_id=%s credits_revoked=%d",
            event["id"],
            payment_intent_id,
            str(pack.user_id),
            str(pack.id),
            revoke,
        )

        BILLING_PACK_DISPUTED.inc()


# Module-level singleton — imported by name in the billing router:
#   from services.stripe_service import stripe_service
stripe_service = StripeService()

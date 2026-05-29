"""Unit/integration tests for Phase 18 Stripe Payments — T-237.

Correctness invariants tested
------------------------------
1. Checkout session creation — user_id in metadata, URL returned
2. Webhook event handling — credits granted on checkout.session.completed
3. Idempotency — duplicate stripe_event_id returns already_processed
4. Signature validation — tampered header → 400
5. IDOR prevention — billing/status returns 404 for wrong user
6. Lazy expiry — get_balance sweeps expired packs (PostgreSQL)
7. FIFO drain order — deduct drains soonest-expiring pack first (PostgreSQL)
8. Dispute revocation — credits revoked capped at min(remaining, balance) (PostgreSQL)
9. Checkout rate limit — 6th request in one hour returns 429
10. Livemode mismatch — mismatched livemode/environment → 400

Tests 1–5 and 9–10 use pure mocking (always run).
Tests 6–8 require TEST_DATABASE_URL (PostgreSQL) — skipped if not set.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from config import settings
from database import get_db
from main import create_app
from middleware.auth import get_current_user
from models import User

# ---------------------------------------------------------------------------
# Integration test guard — PostgreSQL required for tests 6, 7, 8
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")

_requires_pg = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — PostgreSQL integration test skipped. "
        "Set to postgresql+asyncpg://postgres:postgres@localhost:5432/test "
        "to run against a real PostgreSQL instance.  T-237."
    ),
)

# ---------------------------------------------------------------------------
# Shared test user
# ---------------------------------------------------------------------------

_USER_A_ID = uuid4()
_USER_B_ID = uuid4()

_USER_A = User(
    id=_USER_A_ID,
    email="user_a@example.com",
    google_id="google-a",
    name="User A",
    avatar_url=None,
    credit_balance=200,
    created_at=datetime.now(UTC),
)
_USER_B = User(
    id=_USER_B_ID,
    email="user_b@example.com",
    google_id="google-b",
    name="User B",
    avatar_url=None,
    credit_balance=0,
    created_at=datetime.now(UTC),
)


# ---------------------------------------------------------------------------
# Redis stub (satisfies the rate-limit middleware; always allows by default)
# ---------------------------------------------------------------------------


class _FakeRedisPipeline:
    def zremrangebyscore(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    def zadd(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    def zcard(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    def expire(self, *args: Any) -> "_FakeRedisPipeline":
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _CountingFakeRedis:
    """FakeRedis that enforces the sliding-window rate limit semantics.

    Mirrors the in-process fallback in RateLimitMiddleware but is Redis-aware
    so the billing_checkout:{user_id} key is properly tracked.
    """

    def __init__(self) -> None:
        self._sets: dict[str, dict[str, float]] = {}

    async def eval(self, script: str, num_keys: int, *args: Any) -> int:
        key = args[0]
        window_start = float(args[2])
        limit = int(args[3])
        member = args[4]
        now_score = float(args[1])

        ss = self._sets.setdefault(key, {})
        expired = [m for m, s in ss.items() if s <= window_start]
        for m in expired:
            del ss[m]
        if len(ss) >= limit:
            return 0
        ss[member] = now_score
        return 1

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline()


class _NoopRedis:
    """Redis stub that always allows every rate-limit check."""

    async def eval(self, *args: Any, **kwargs: Any) -> int:
        return 1

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline()


# ---------------------------------------------------------------------------
# DB stubs
# ---------------------------------------------------------------------------


class _NoopSession:
    """Minimal async session stub for tests that don't need real DB."""

    async def execute(self, statement: Any) -> Any:
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value = iter([])
        return result

    async def scalar(self, statement: Any) -> Any:
        return None

    async def flush(self) -> None:
        pass

    def add(self, obj: Any) -> None:
        pass

    def begin_nested(self) -> "_SavepointCtx":
        return _SavepointCtx()


class _SavepointCtx:
    """Savepoint context that always succeeds (no IntegrityError)."""

    async def __aenter__(self) -> "_SavepointCtx":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False  # never suppress exceptions


class _IntegrityErrorSavepoint:
    """Savepoint that raises IntegrityError on flush — simulates duplicate event."""

    async def __aenter__(self) -> "_IntegrityErrorSavepoint":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False


class _IdempotencyFakeSession:
    """Session stub that raises IntegrityError on flush after the first add().

    Used to simulate the duplicate-event path in the webhook handler:
      - First request: flush succeeds.
      - Second request: flush raises IntegrityError (UNIQUE constraint on
        stripe_event_id), causing the router to return {"status": "already_processed"}.
    """

    def __init__(self, raise_on_flush: bool = False) -> None:
        self._raise = raise_on_flush
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> Any:
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    async def scalar(self, statement: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def begin_nested(self) -> "_ConditionalSavepoint":
        return _ConditionalSavepoint(self)

    async def flush(self) -> None:
        if self._raise:
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError(None, None, Exception("UNIQUE constraint"))


class _ConditionalSavepoint:
    def __init__(self, session: _IdempotencyFakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> "_ConditionalSavepoint":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False  # propagate exceptions


class _StatusCheckSession:
    """Session stub for billing/status IDOR test.

    Returns None for any db.scalar() call — simulates the case where
    the queried session_id exists for user_A but is not visible to user_B.
    """

    async def scalar(self, statement: Any) -> Any:
        return None  # user_B sees nothing (404 expected)

    async def execute(self, statement: Any) -> Any:
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    def begin_nested(self) -> _SavepointCtx:
        return _SavepointCtx()

    async def flush(self) -> None:
        pass

    def add(self, obj: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# App factory helpers
# ---------------------------------------------------------------------------


def _make_app(
    *,
    user: User = _USER_A,
    redis: Any = None,
    db_override: Any = None,
):
    """Build a FastAPI app with injected auth + optional DB override."""
    if redis is None:
        redis = _NoopRedis()
    app = create_app(redis_client=redis)

    async def _fake_user():
        return user

    app.dependency_overrides[get_current_user] = _fake_user

    if db_override is not None:
        # db_override is either a session instance or a callable factory.
        if callable(db_override) and not isinstance(db_override, type):
            app.dependency_overrides[get_db] = db_override
        else:

            async def _fake_db():
                yield db_override

            app.dependency_overrides[get_db] = _fake_db

    return app


# ===========================================================================
# Test 1 — Checkout session creation
# ===========================================================================


@pytest.mark.asyncio
async def test_checkout_session_creation() -> None:
    """Checkout creates a Stripe session and embeds user_id in metadata.

    Invariant: user_id must be in metadata so the webhook handler can
    grant credits without trusting any user-controllable field.  An empty
    or absent metadata.user_id would allow any attacker-crafted webhook
    event to grant credits to an arbitrary account.
    """
    from services.stripe_service import StripeService

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/test"

    svc = StripeService()
    user_id = uuid4()

    # settings.stripe_secret_key / stripe_success_url default to "" — the
    # 503 guards inside create_checkout_session would fire before we ever
    # reach the patched create_async.  Stub both for the duration of the test.
    with (
        patch.object(settings, "stripe_secret_key", "sk_test_dummy"),
        patch.object(
            settings, "stripe_success_url", "https://example.test/billing"
        ),
        patch.object(
            settings, "stripe_cancel_url", "https://example.test/billing"
        ),
        patch(
            "stripe.checkout.Session.create_async",
            new_callable=AsyncMock,
            return_value=mock_session,
        ) as mock_create,
    ):
        result = await svc.create_checkout_session(
            user_id=user_id,
            user_email="test@example.com",
        )

    assert result == "https://checkout.stripe.com/test"
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert "metadata" in call_kwargs, "metadata must be passed to Stripe"
    assert call_kwargs["metadata"] == {"user_id": str(user_id)}, (
        "metadata must contain user_id so the webhook can resolve the user "
        "without trusting any user-controllable field."
    )


# ===========================================================================
# Test 2 — Webhook checkout.session.completed grants credits
# ===========================================================================


@pytest.mark.asyncio
async def test_webhook_checkout_completed_grants_credits() -> None:
    """handle_event credits the user when checkout.session.completed is paid.

    Invariant: credits must only be granted when payment_status == 'paid'.
    Granting credits on any other status (e.g. 'unpaid', 'no_payment_required')
    allows free credit acquisition without a real payment.
    """
    from services.credit_service import credit_service
    from services.stripe_service import StripeService

    user_id = uuid4()
    session_id = f"cs_test_{uuid4().hex}"
    event_created = int(time.time())

    event = {
        "id": f"evt_{uuid4().hex}",
        "type": "checkout.session.completed",
        "created": event_created,
        "livemode": False,
        "data": {
            "object": {
                "id": session_id,
                "payment_status": "paid",
                "payment_intent": f"pi_{uuid4().hex}",
                "metadata": {"user_id": str(user_id)},
                "customer_email": "test@example.com",
            }
        },
    }

    # Provide a minimal fake DB that satisfies the ORM calls inside
    # _handle_checkout_completed (db.add + db.flush).
    class _CheckoutDB:
        def __init__(self) -> None:
            self.added: list[Any] = []
            self._user = User(
                id=user_id,
                email="test@example.com",
                google_id="g-test",
                name="Test",
                credit_balance=0,
                created_at=datetime.now(UTC),
            )

        async def execute(self, statement: Any) -> Any:
            result = MagicMock()
            result.scalar_one_or_none.return_value = self._user
            return result

        def add(self, obj: Any) -> None:
            self.added.append(obj)

        async def flush(self) -> None:
            for obj in self.added:
                if not hasattr(obj, "id") or obj.id is None:
                    object.__setattr__(obj, "id", uuid4())

    db = _CheckoutDB()
    svc = StripeService()

    with patch.object(
        credit_service,
        "credit",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ) as mock_credit:
        await svc.handle_event(db, event)

    mock_credit.assert_called_once()
    credit_call_kwargs = mock_credit.call_args
    # Second positional arg is user_id, third is amount.
    assert (
        credit_call_kwargs[0][1] == user_id
    ), "Credits must be granted to the correct user"
    credited_amount = credit_call_kwargs[1].get("amount", credit_call_kwargs[0][2])
    assert (
        credited_amount == settings.stripe_credits_per_purchase
    ), "Credits granted must match settings.stripe_credits_per_purchase"


# ===========================================================================
# Test 3 — Idempotency: duplicate event returns already_processed
# ===========================================================================


@pytest.mark.asyncio
async def test_webhook_idempotency() -> None:
    """Duplicate stripe_event_id returns {"status": "already_processed"}.

    Invariant: exactly one credit grant per stripe_event_id.  Without the
    idempotency guard, Stripe's 72-hour retry window means every delivery
    failure causes double-crediting on the retry.
    """
    stripe_event_id = f"evt_{uuid4().hex}"
    event_type = "checkout.session.completed"

    # Build a valid-ish event dict (used by both mock construct_event calls).
    mock_event = {
        "id": stripe_event_id,
        "type": event_type,
        "created": int(time.time()),
        "livemode": settings.environment.lower() == "production",
        "data": {
            "object": {
                "id": f"cs_test_{uuid4().hex}",
                "payment_status": "paid",
                "metadata": {"user_id": str(uuid4())},
            }
        },
    }

    # First request: INSERT succeeds.
    first_db = _IdempotencyFakeSession(raise_on_flush=False)
    # Second request: INSERT raises IntegrityError (duplicate stripe_event_id).
    second_db = _IdempotencyFakeSession(raise_on_flush=True)

    # Alternate which fake DB get_db returns.
    call_count = 0
    sessions = [first_db, second_db]

    async def _alternating_db():
        nonlocal call_count
        yield sessions[call_count % 2]
        call_count += 1

    app = create_app(redis_client=_NoopRedis())
    app.dependency_overrides[get_db] = _alternating_db

    with (
        patch("stripe.Webhook.construct_event", return_value=mock_event),
        patch(
            "services.stripe_service.stripe_service.handle_event",
            new_callable=AsyncMock,
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.post(
                "/billing/webhook",
                content=b'{"test":"payload"}',
                headers={"Stripe-Signature": "t=1,v1=abc"},
            )
            resp2 = await client.post(
                "/billing/webhook",
                content=b'{"test":"payload"}',
                headers={"Stripe-Signature": "t=1,v1=abc"},
            )

    assert resp1.status_code == 200
    assert resp1.json()["status"] == "ok", "First delivery must succeed"

    assert resp2.status_code == 200
    assert resp2.json()["status"] == "already_processed", (
        "Duplicate stripe_event_id must return 'already_processed' — "
        "this prevents double-crediting on Stripe retry."
    )


# ===========================================================================
# Test 4 — Invalid Stripe signature returns 400
# ===========================================================================


@pytest.mark.asyncio
async def test_webhook_invalid_signature() -> None:
    """A tampered or missing Stripe-Signature header returns HTTP 400.

    Invariant: all credits flow through this webhook.  Without HMAC
    validation, any HTTP client can inject fake checkout.session.completed
    events and self-credit unlimited credits.
    """
    app = create_app(redis_client=_NoopRedis())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/billing/webhook",
            content=b'{"id":"evt_fake","type":"checkout.session.completed"}',
            headers={"Stripe-Signature": "t=9999,v1=tampered_signature_value"},
        )

    assert resp.status_code == 400, (
        "Tampered Stripe-Signature must be rejected with HTTP 400. "
        "Accepting it would allow unauthenticated credit injection."
    )


# ===========================================================================
# Test 5 — IDOR prevention: billing/status 404 for wrong user
# ===========================================================================


@pytest.mark.asyncio
async def test_billing_status_idor_prevention() -> None:
    """GET /billing/status returns 404 when session_id belongs to a different user.

    Invariant: returning 403 would confirm the session exists for another
    user (resource-existence leakage).  404 reveals nothing — it covers
    both "session not found" and "session belongs to someone else".
    """
    app = _make_app(user=_USER_B, db_override=_StatusCheckSession())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/billing/status",
            params={"session_id": "cs_test_belongs_to_user_a"},
            headers={"Authorization": "Bearer fake-token"},
        )

    assert resp.status_code == 404, (
        "GET /billing/status must return 404 (not 403, not 200) when the "
        "session_id belongs to a different user.  403 would confirm the "
        "session exists for someone else (resource-existence leakage)."
    )


# ===========================================================================
# Test 6 — Lazy expiry: get_balance sweeps expired packs (PostgreSQL)
# ===========================================================================


@_requires_pg
@pytest.mark.asyncio
async def test_lazy_expiry_sweeps_expired_packs() -> None:
    """get_balance() sets status='expired' and credits_remaining=0 on lapsed packs.

    Invariant: expired credits must be swept before reading the balance to
    prevent ghost credits.  Without lazy expiry, a user with only expired
    packs could appear to have a positive balance and pass credit checks.
    """
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from models import Base
    from models.stripe_credit_pack import StripeCreditPack
    from services.credit_service import CreditService

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    svc = CreditService(redis_client=redis)

    user_id = uuid4()
    async with Session() as session:
        async with session.begin():
            user = User(
                id=user_id,
                email=f"expiry_{user_id.hex[:8]}@example.com",
                google_id=f"g-expiry-{user_id.hex[:8]}",
                name="Expiry Test",
                credit_balance=200,
                created_at=datetime.now(UTC),
            )
            session.add(user)

            pack = StripeCreditPack(
                id=uuid4(),
                user_id=user_id,
                stripe_session_id=f"cs_test_expiry_{uuid4().hex}",
                credits_purchased=200,
                credits_remaining=200,
                price_cents=900,
                status="active",
                purchased_at=datetime.now(UTC) - timedelta(days=35),
                expires_at=datetime.now(UTC) - timedelta(days=5),  # expired 5 days ago
                created_at=datetime.now(UTC) - timedelta(days=35),
            )
            session.add(pack)

    async with Session() as session:
        async with session.begin():
            balance = await svc.get_balance(session, user_id)

            from sqlalchemy import select

            result = await session.execute(
                select(StripeCreditPack).where(StripeCreditPack.user_id == user_id)
            )
            swept_pack = result.scalar_one_or_none()

    assert swept_pack is not None
    assert (
        swept_pack.status == "expired"
    ), "Lazy expiry must set pack.status = 'expired'"
    assert (
        swept_pack.credits_remaining == 0
    ), "Lazy expiry must set pack.credits_remaining = 0"
    assert balance == 0, "Balance after sweeping the only expired pack must be 0"

    await redis.aclose()
    await engine.dispose()


# ===========================================================================
# Test 7 — FIFO drain order: deduct drains soonest-expiring pack first
# ===========================================================================


@_requires_pg
@pytest.mark.asyncio
async def test_fifo_drain_order() -> None:
    """CreditService.deduct() drains soonest-expiring pack first.

    Invariant: FIFO drain (ORDER BY expires_at ASC) prevents users from
    effectively extending their credits by leaving older packs untouched.
    A LIFO or random drain would waste the newest packs first.
    """
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from models import Base
    from models.stripe_credit_pack import StripeCreditPack
    from services.credit_service import CreditService

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    svc = CreditService(redis_client=redis)

    user_id = uuid4()
    pack_a_id = uuid4()
    pack_b_id = uuid4()

    async with Session() as session:
        async with session.begin():
            user = User(
                id=user_id,
                email=f"fifo_{user_id.hex[:8]}@example.com",
                google_id=f"g-fifo-{user_id.hex[:8]}",
                name="FIFO Test",
                credit_balance=200,
                created_at=datetime.now(UTC),
            )
            session.add(user)

            # pack_a expires in 5 days (soonest — should be drained first)
            pack_a = StripeCreditPack(
                id=pack_a_id,
                user_id=user_id,
                stripe_session_id=f"cs_test_fifo_a_{uuid4().hex}",
                credits_purchased=100,
                credits_remaining=100,
                price_cents=900,
                status="active",
                purchased_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=5),
                created_at=datetime.now(UTC),
            )
            session.add(pack_a)

            # pack_b expires in 15 days (later — should NOT be touched)
            pack_b = StripeCreditPack(
                id=pack_b_id,
                user_id=user_id,
                stripe_session_id=f"cs_test_fifo_b_{uuid4().hex}",
                credits_purchased=100,
                credits_remaining=100,
                price_cents=900,
                status="active",
                purchased_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=15),
                created_at=datetime.now(UTC),
            )
            session.add(pack_b)

    async with Session() as session:
        async with session.begin():
            await svc.deduct(session, user_id, 50, "test_fifo_drain")

            from sqlalchemy import select

            res = await session.execute(
                select(StripeCreditPack).where(StripeCreditPack.user_id == user_id)
            )
            packs = {p.id: p for p in res.scalars().all()}

    assert (
        packs[pack_a_id].credits_remaining == 50
    ), "pack_a (expires in 5 days) must be drained first — 100 - 50 = 50 remaining"
    assert packs[pack_b_id].credits_remaining == 100, (
        "pack_b (expires in 15 days) must be untouched — "
        "FIFO drains soonest-expiring pack first"
    )

    await redis.aclose()
    await engine.dispose()


# ===========================================================================
# Test 8 — Dispute revocation: credits revoked = min(remaining, balance)
# ===========================================================================


@_requires_pg
@pytest.mark.asyncio
async def test_dispute_revocation() -> None:
    """Dispute revocation is capped at min(pack.credits_remaining, user.credit_balance).

    Invariant: revoking the full purchase amount from a partially-spent pack
    would push credit_balance negative (violates DB CHECK constraint).  The
    min() cap ensures we only revoke what the user still has.
    """
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from models import Base
    from models.stripe_credit_pack import StripeCreditPack
    from services.stripe_service import StripeService

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    svc = StripeService()

    user_id = uuid4()
    payment_intent_id = f"pi_{uuid4().hex}"

    async with Session() as session:
        async with session.begin():
            user = User(
                id=user_id,
                email=f"dispute_{user_id.hex[:8]}@example.com",
                google_id=f"g-dispute-{user_id.hex[:8]}",
                name="Dispute Test",
                credit_balance=100,  # user already spent 50 of the 150 remaining
                created_at=datetime.now(UTC),
            )
            session.add(user)

            pack = StripeCreditPack(
                id=uuid4(),
                user_id=user_id,
                stripe_session_id=f"cs_test_dispute_{uuid4().hex}",
                stripe_payment_intent_id=payment_intent_id,
                credits_purchased=200,
                credits_remaining=150,  # 50 credits already spent
                price_cents=900,
                status="active",
                purchased_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=25),
                created_at=datetime.now(UTC),
            )
            session.add(pack)

    dispute_event = {
        "id": f"evt_{uuid4().hex}",
        "type": "charge.dispute.created",
        "created": int(time.time()),
        "livemode": False,
        "data": {
            "object": {
                "id": f"dp_{uuid4().hex}",
                "payment_intent": payment_intent_id,
            }
        },
    }

    async with Session() as session:
        async with session.begin():
            await svc.handle_event(session, dispute_event)

            from sqlalchemy import select

            res_pack = await session.execute(
                select(StripeCreditPack).where(
                    StripeCreditPack.stripe_payment_intent_id == payment_intent_id
                )
            )
            updated_pack = res_pack.scalar_one_or_none()

            from models import User as UserModel

            res_user = await session.execute(
                select(UserModel).where(UserModel.id == user_id)
            )
            updated_user = res_user.scalar_one_or_none()

    assert updated_pack is not None
    assert (
        updated_pack.status == "disputed"
    ), "Disputed pack must have status='disputed'"
    assert (
        updated_pack.credits_remaining == 0
    ), "Disputed pack must have credits_remaining=0"
    # Revocation = min(credits_remaining=150, credit_balance=100) = 100
    assert (
        updated_user.credit_balance == 0
    ), "User credit_balance must be 0 after revoking min(150, 100) = 100 credits"

    await redis.aclose()
    await engine.dispose()


# ===========================================================================
# Test 9 — Checkout rate limit: 6th request returns 429
# ===========================================================================


@pytest.mark.asyncio
async def test_checkout_rate_limit() -> None:
    """The 6th POST /billing/checkout within one hour returns HTTP 429.

    Invariant: without this limit, a script can create hundreds of Stripe
    Checkout Sessions per hour, inflating Stripe API costs and potentially
    triggering Stripe's fraud-detection for the platform account.
    """
    counting_redis = _CountingFakeRedis()

    async def _fake_user():
        return _USER_A

    app = create_app(redis_client=counting_redis)
    app.dependency_overrides[get_current_user] = _fake_user

    async def _fake_db():
        yield _NoopSession()

    app.dependency_overrides[get_db] = _fake_db

    # The rate-limit middleware extracts user_id from the Authorization
    # header via decode_access_token_claims().  Without a real JWT, that
    # returns None and the per-user billing_checkout limit never engages.
    # Patch it to return a valid claims dict so the limit is enforced.
    with (
        patch(
            "middleware.rate_limit.decode_access_token_claims",
            return_value={"sub": str(_USER_A_ID)},
        ),
        patch(
            "services.stripe_service.stripe_service.create_checkout_session",
            new_callable=AsyncMock,
            return_value="https://checkout.stripe.com/test",
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            responses = []
            for _ in range(6):
                resp = await client.post(
                    "/billing/checkout",
                    headers={"Authorization": "Bearer fake-token"},
                )
                responses.append(resp)

    statuses = [r.status_code for r in responses]
    assert all(
        s == 200 for s in statuses[:5]
    ), f"First 5 checkout requests must succeed (200), got: {statuses[:5]}"
    assert responses[5].status_code == 429, (
        f"6th checkout request must be rate-limited (429), "
        f"got: {responses[5].status_code}"
    )
    detail = responses[5].json().get("detail", "")
    assert (
        "5 purchases per hour" in detail
    ), f"Rate-limit detail must mention '5 purchases per hour', got: {detail!r}"


# ===========================================================================
# Test 10 — Livemode mismatch returns 400
# ===========================================================================


@pytest.mark.asyncio
async def test_webhook_livemode_mismatch() -> None:
    """Webhook event with livemode != server environment returns HTTP 400.

    Invariant: a test-mode endpoint receiving live events (or vice versa)
    would silently grant credits from test payments that never charged real
    money.  The livemode guard catches this misconfiguration at the first
    webhook delivery rather than silently granting credits.
    """
    # Force a livemode mismatch: event says livemode=True, but we're in
    # development (non-production) environment.
    is_production = settings.environment.lower() == "production"
    mismatched_livemode = not is_production  # opposite of what server expects

    mock_event = {
        "id": f"evt_{uuid4().hex}",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "livemode": mismatched_livemode,  # wrong livemode for this environment
        "data": {"object": {}},
    }

    app = create_app(redis_client=_NoopRedis())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("stripe.Webhook.construct_event", return_value=mock_event):
            resp = await client.post(
                "/billing/webhook",
                content=b'{"test":"payload"}',
                headers={"Stripe-Signature": "t=1,v1=abc"},
            )

    assert resp.status_code == 400, (
        "Livemode mismatch must return HTTP 400.  Accepting it would grant "
        "credits from test payments with no real money charged."
    )
    assert "livemode" in resp.json().get("detail", "").lower(), (
        "Response detail must mention 'livemode' so operators know why the "
        "webhook was rejected."
    )

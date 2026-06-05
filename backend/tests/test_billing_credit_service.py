"""Behavioural tests for the BillingCreditPack credit path + debt-first grant (T-294).

These exercise the migrated ``CreditService`` against a real PostgreSQL + Redis
(skipped when ``TEST_DATABASE_URL`` is unset, like the other billing integration
tests). They cover the parts the mocked ``test_credit_service.py`` cannot:

- ``grant_credits_with_debt_recovery`` repays pending ``billing_credit_debts``
  oldest-first BEFORE any usable surplus, writing the two-component
  ``debt_recovery:billing:{debt}:{pack}`` audit row and the single surplus row;
- lazy expiry moves the lapsed remainder into ``credits_expired``;
- FIFO drain increments ``credits_consumed``;
- the conservation invariant ``remaining + consumed + expired + debt_recovered ==
  purchased`` holds across grant / drain / expiry;
- the SAVEPOINT/IntegrityError idempotency barrier rolls a duplicate grant back to a
  no-op (the credit_ledger reason-uniqueness index from migration 0018 is recreated
  here, since ``create_all`` builds only ORM-declared constraints).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from models import BillingCreditDebt, BillingCreditPack, CreditLedger, User
from services.credit_service import CreditService

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")

_requires_pg = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — billing credit-service integration test "
        "skipped. Set it (and a real Redis) to exercise the debt-first grant, "
        "expiry/consumed accounting, and the idempotency barrier. T-294."
    ),
)

pytestmark = [_requires_pg, pytest.mark.asyncio]

# The two credit_ledger reason-uniqueness indexes the grant helper relies on (they
# live in migration 0018, not the ORM metadata that create_all builds).
_LEDGER_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_ledger_billing_purchase_reason "
    "ON credit_ledger(reason) WHERE reason LIKE 'billing_purchase:%'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_ledger_billing_reversal_reason "
    "ON credit_ledger(reason) "
    "WHERE reason LIKE 'refund:billing:%' OR reason LIKE 'debt_recovery:billing:%'",
)


async def _setup() -> tuple:
    from redis.asyncio import Redis

    from models import Base

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _LEDGER_INDEX_SQL:
            await conn.execute(text(stmt))
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    return engine, session_factory, redis


def _new_user(balance: int = 0) -> User:
    uid = uuid4()
    return User(
        id=uid,
        email=f"grant_{uid.hex[:8]}@example.com",
        google_id=f"g-grant-{uid.hex[:8]}",
        name="Grant Test",
        credit_balance=balance,
        created_at=datetime.now(UTC),
    )


def _pack(user_id: UUID, *, credits: int, **overrides) -> BillingCreditPack:
    base = dict(
        id=uuid4(),
        user_id=user_id,
        provider="lemonsqueezy",
        provider_checkout_id=f"chk_{uuid4().hex}",
        credits_purchased=credits,
        credits_remaining=credits,
        price_cents=900,
        currency="USD",
        paid_item_amount_cents=900,
        status="active",
        purchased_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    base.update(overrides)
    return BillingCreditPack(**base)


def _conservation_ok(pack: BillingCreditPack) -> bool:
    return (
        pack.credits_remaining
        + pack.credits_consumed
        + pack.credits_expired
        + pack.credits_debt_recovered
        == pack.credits_purchased
    )


async def _seed_debt(
    session: AsyncSession, user_id: UUID, *, owed: int
) -> tuple[BillingCreditPack, BillingCreditDebt]:
    """A reversed source pack + a pending debt referencing it (RESTRICT FK)."""
    source = _pack(
        user_id,
        credits=owed,
        credits_remaining=0,
        credits_revoked=owed,
        status="refunded",
    )
    session.add(source)
    await session.flush()
    debt = BillingCreditDebt(
        id=uuid4(),
        user_id=user_id,
        source_pack_id=source.id,
        provider="lemonsqueezy",
        provider_order_id=f"ord_src_{uuid4().hex[:8]}",
        credits_owed=owed,
        credits_recovered=0,
        status="pending",
        reason="refund_exceeded_remaining",
    )
    session.add(debt)
    await session.flush()
    return source, debt


# ---------------------------------------------------------------------------
# Debt-first grant
# ---------------------------------------------------------------------------


async def test_grant_repays_debt_before_surplus() -> None:
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    user = _new_user(balance=0)
    reason = f"billing_purchase:lemonsqueezy:ord_{uuid4().hex[:8]}"
    try:
        async with Session() as session:
            async with session.begin():
                session.add(user)
                await session.flush()
                _src, debt = await _seed_debt(session, user.id, owed=50)
                pack = _pack(user.id, credits=200)
                session.add(pack)
                await session.flush()
                entry = await svc.grant_credits_with_debt_recovery(
                    session,
                    user_id=user.id,
                    pack=pack,
                    granted_credits=200,
                    ledger_reason=reason,
                )
                pack_id, debt_id = pack.id, debt.id

        async with Session() as session:
            pack = await session.get(BillingCreditPack, pack_id)
            debt = await session.get(BillingCreditDebt, debt_id)
            user_row = await session.get(User, user.id)
            recov = (
                await session.execute(
                    select(CreditLedger).where(
                        CreditLedger.reason
                        == f"debt_recovery:billing:{debt_id}:{pack_id}"
                    )
                )
            ).scalar_one()
            purchase = (
                await session.execute(
                    select(CreditLedger).where(CreditLedger.reason == reason)
                )
            ).scalar_one()

        assert entry is not None
        # Debt fully repaid out of the new pack.
        assert debt.credits_recovered == 50 and debt.status == "recovered"
        assert pack.credits_debt_recovered == 50
        assert pack.credits_remaining == 150
        # Only the surplus (200 - 50) becomes usable balance.
        assert user_row.credit_balance == 150
        assert purchase.amount == 150
        assert recov.amount == 0  # the debt-recovery row is a zero-amount audit row
        assert _conservation_ok(pack)
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_grant_all_to_debt_yields_zero_surplus() -> None:
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    user = _new_user(balance=0)
    reason = f"billing_purchase:lemonsqueezy:ord_{uuid4().hex[:8]}"
    try:
        async with Session() as session:
            async with session.begin():
                session.add(user)
                await session.flush()
                await _seed_debt(session, user.id, owed=200)
                pack = _pack(user.id, credits=200)
                session.add(pack)
                await session.flush()
                await svc.grant_credits_with_debt_recovery(
                    session,
                    user_id=user.id,
                    pack=pack,
                    granted_credits=200,
                    ledger_reason=reason,
                )
                pack_id = pack.id

        async with Session() as session:
            pack = await session.get(BillingCreditPack, pack_id)
            user_row = await session.get(User, user.id)
            purchase = (
                await session.execute(
                    select(CreditLedger).where(CreditLedger.reason == reason)
                )
            ).scalar_one()

        assert pack.credits_debt_recovered == 200 and pack.credits_remaining == 0
        # Per the Plan, status is NOT flipped to consumed here — it stays active
        # (a 0-remaining pack lazy-expires cleanly later).
        assert pack.status == "active"
        assert user_row.credit_balance == 0  # no usable surplus
        assert purchase.amount == 0
        assert _conservation_ok(pack)
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_grant_with_no_debt_is_full_surplus() -> None:
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    user = _new_user(balance=10)
    reason = f"billing_purchase:lemonsqueezy:ord_{uuid4().hex[:8]}"
    try:
        async with Session() as session:
            async with session.begin():
                session.add(user)
                await session.flush()
                pack = _pack(user.id, credits=200)
                session.add(pack)
                await session.flush()
                await svc.grant_credits_with_debt_recovery(
                    session,
                    user_id=user.id,
                    pack=pack,
                    granted_credits=200,
                    ledger_reason=reason,
                )
                pack_id = pack.id

        async with Session() as session:
            pack = await session.get(BillingCreditPack, pack_id)
            user_row = await session.get(User, user.id)
            recov = (
                (
                    await session.execute(
                        select(CreditLedger).where(
                            CreditLedger.user_id == user.id,
                            CreditLedger.reason.like("debt_recovery:billing:%"),
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert pack.credits_remaining == 200 and pack.credits_debt_recovered == 0
        assert user_row.credit_balance == 210  # 10 + 200
        assert recov == []  # no debt-recovery rows when there is no debt
        assert _conservation_ok(pack)
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_grant_is_idempotent_on_duplicate_reason() -> None:
    """A second grant with the same ledger reason rolls back to a no-op (SAVEPOINT)."""
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    user = _new_user(balance=0)
    reason = f"billing_purchase:lemonsqueezy:ord_{uuid4().hex[:8]}"
    try:
        async with Session() as session:
            async with session.begin():
                session.add(user)
                await session.flush()
                pack1 = _pack(user.id, credits=200)
                session.add(pack1)
                await session.flush()
                first = await svc.grant_credits_with_debt_recovery(
                    session,
                    user_id=user.id,
                    pack=pack1,
                    granted_credits=200,
                    ledger_reason=reason,
                )

        async with Session() as session:
            async with session.begin():
                pack2 = _pack(user.id, credits=200)
                session.add(pack2)
                await session.flush()
                second = await svc.grant_credits_with_debt_recovery(
                    session,
                    user_id=user.id,
                    pack=pack2,
                    granted_credits=200,
                    ledger_reason=reason,
                )
                pack2_id = pack2.id

        async with Session() as session:
            user_row = await session.get(User, user.id)
            pack2 = await session.get(BillingCreditPack, pack2_id)
            rows = (
                (
                    await session.execute(
                        select(CreditLedger).where(CreditLedger.reason == reason)
                    )
                )
                .scalars()
                .all()
            )

        assert first is not None and second is None
        assert user_row.credit_balance == 200  # granted exactly once
        assert len(rows) == 1  # the unique reason index admitted only one row
        # The duplicate grant's savepoint rolled back — pack2 was not drained.
        assert pack2.credits_remaining == 200 and pack2.credits_debt_recovered == 0
    finally:
        await redis.aclose()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Expiry / consumed accounting + conservation
# ---------------------------------------------------------------------------


async def test_lazy_expiry_segregates_value_into_credits_expired() -> None:
    """Expired value moves to credits_expired (so a later reversal owes no debt for
    it) and leaves credits_remaining at 0 — the expiry side of 'no debt for expired'."""
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    user = _new_user(balance=120)
    try:
        async with Session() as session:
            async with session.begin():
                session.add(user)
                await session.flush()
                pack = _pack(
                    user.id,
                    credits=120,
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
                session.add(pack)
                await session.flush()
                pack_id = pack.id

        async with Session() as session:
            async with session.begin():
                balance = await svc.get_balance(session, user.id)

        async with Session() as session:
            pack = await session.get(BillingCreditPack, pack_id)

        assert balance == 0
        assert pack.status == "expired"
        assert pack.credits_remaining == 0
        assert pack.credits_expired == 120
        assert _conservation_ok(pack)
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_fifo_drain_increments_consumed_and_conserves() -> None:
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    user = _new_user(balance=120)
    try:
        async with Session() as session:
            async with session.begin():
                session.add(user)
                await session.flush()
                pack = _pack(user.id, credits=120)
                session.add(pack)
                await session.flush()
                pack_id = pack.id

        async with Session() as session:
            async with session.begin():
                await svc.deduct(session, user.id, 30, "generate")

        async with Session() as session:
            pack = await session.get(BillingCreditPack, pack_id)

        assert pack.credits_remaining == 90
        assert pack.credits_consumed == 30
        assert pack.status == "active"
        assert _conservation_ok(pack)
    finally:
        await redis.aclose()
        await engine.dispose()

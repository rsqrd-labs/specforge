"""Phase-25 (Lemon Squeezy billing) money-math behaviours that a source-grep
harness cannot run — the T-306 behavioural deliverable.

The per-task suites (``test_billing_*.py``) already cover the individual money
paths in isolation: refund floor/clamp + partial proportional math + the
unprocessed-delta replay gate (``test_billing_order_refunded``), debt creation +
recovery-before-surplus and expired-never-debt (``test_billing_credit_service`` /
``test_billing_order_refunded``), duplicate ``order_created``/inbox no-double-credit
and forged-``user_id``/nonce-mismatch grants-nothing (``test_billing_order_created``),
``/billing/status`` IDOR 404 (``test_billing_router``), queue-outage recovery +
stale-``processing`` reclaim (``test_billing_worker``/``test_billing_queue``),
reconcile no-auto-grant + cursor-advance (``test_billing_reconcile``),
admin-correction authz + idempotency + debt-first (``test_billing_admin_correction``),
and backfill balance-preservation + ``disputed credits_revoked=0``
(``test_billing_migration_0018``).

This file adds the two cross-cutting behaviours that none of those exercise:

1. **Concurrent deduct ↔ refund deadlock-safety (R8).** ``deduct`` and
   ``apply_refund_reversal`` both lock ``user → packs (ORDER BY expires_at ASC)`` in
   the *same* order, so two of them racing over the same user can never deadlock.
   The existing suites only assert each in isolation; this runs them concurrently on
   two real connections and asserts no Postgres deadlock/serialization error plus the
   post-state invariants (``balance == Σ remaining``, ``balance >= 0``, per-pack
   conservation).
2. **Full purchase→spend→reverse→debt→repurchase lifecycle.** A single end-to-end
   flow through ``deduct`` then a reversal that exceeds the still-held remaining
   (creating recoverable debt) then a fresh grant that repays the debt *before* any
   usable surplus — the real-world reversal-then-recovery sequence, asserted as one
   conserved story rather than as isolated units.

Gated on ``TEST_DATABASE_URL`` (+ a real Redis) like the other billing integration
tests, so it skips cleanly without Postgres.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from models import BillingCreditDebt, BillingCreditPack, CreditLedger, User
from services.credit_service import CreditService, InsufficientCreditsError

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")

_requires_pg = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — Phase-25 money-math integration test skipped. "
        "Set it (and a real Redis) to exercise concurrent deduct↔refund deadlock-"
        "safety and the reversal-then-recovery lifecycle. T-306."
    ),
)

pytestmark = [_requires_pg, pytest.mark.asyncio]

# Postgres SQLSTATEs that mean the concurrency control gave up rather than serialised
# cleanly — the failure modes a consistent lock order must make impossible.
_DEADLOCK_SQLSTATE = "40P01"
_SERIALIZATION_SQLSTATE = "40001"

# The credit_ledger reason-uniqueness indexes the grant/refund helpers rely on (they
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
        email=f"mm_{uid.hex[:8]}@example.com",
        google_id=f"g-mm-{uid.hex[:8]}",
        name="MoneyMath Test",
        credit_balance=balance,
        created_at=datetime.now(UTC),
    )


def _pack(user_id: UUID, *, credits: int, **overrides) -> BillingCreditPack:
    base = dict(
        id=uuid4(),
        user_id=user_id,
        provider="lemonsqueezy",
        provider_checkout_id=f"chk_{uuid4().hex}",
        provider_order_id=f"ord_{uuid4().hex[:10]}",
        credits_purchased=credits,
        credits_remaining=credits,
        price_cents=900,
        currency="USD",
        paid_item_amount_cents=900,
        provider_order_total_cents=900,
        status="active",
        purchased_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    base.update(overrides)
    return BillingCreditPack(**base)


def _is_deadlock(exc: BaseException) -> bool:
    """True for a Postgres deadlock/serialization failure (the forbidden outcome)."""
    if not isinstance(exc, DBAPIError):
        return False
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    return sqlstate in (_DEADLOCK_SQLSTATE, _SERIALIZATION_SQLSTATE)


async def _cleanup_users(Session: async_sessionmaker, user_ids: list[UUID]) -> None:
    """Delete every row this suite created so it never pollutes the shared test DB
    (global-scan tests like reconcile lane 2/3 must not see our packs). Order honours
    the RESTRICT FK: debts → packs → ledger → users."""
    if not user_ids:
        return
    async with Session() as db:
        async with db.begin():
            await db.execute(
                BillingCreditDebt.__table__.delete().where(
                    BillingCreditDebt.user_id.in_(user_ids)
                )
            )
            await db.execute(
                BillingCreditPack.__table__.delete().where(
                    BillingCreditPack.user_id.in_(user_ids)
                )
            )
            await db.execute(
                CreditLedger.__table__.delete().where(
                    CreditLedger.user_id.in_(user_ids)
                )
            )
            await db.execute(User.__table__.delete().where(User.id.in_(user_ids)))


async def _assert_user_consistent(Session: async_sessionmaker, user_id: UUID) -> None:
    """The cross-row money invariants a partial/rolled-back race would break."""
    async with Session() as session:
        user = await session.get(User, user_id)
        packs = (
            (
                await session.execute(
                    select(BillingCreditPack).where(
                        BillingCreditPack.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
    balance = int(user.credit_balance or 0)
    assert balance >= 0, f"balance went negative: {balance}"
    # Usable balance is exactly the sum of still-held pack credits.
    assert balance == sum(p.credits_remaining for p in packs), (
        f"balance {balance} != Σ remaining "
        f"{sum(p.credits_remaining for p in packs)}"
    )
    # Per-pack lifetime conservation (also a DB CHECK, asserted post-race here).
    for p in packs:
        assert (
            p.credits_remaining
            + p.credits_consumed
            + p.credits_expired
            + p.credits_debt_recovered
            <= p.credits_purchased
        ), f"pack {p.id} over-accounts its purchased credits"


async def test_concurrent_deduct_and_refund_are_deadlock_safe() -> None:
    """deduct ↔ apply_refund_reversal racing on one user never deadlocks (R8).

    Both paths take the canonical ``user → packs (expires_at ASC) FOR UPDATE`` lock
    order, so a deadlock (40P01) is impossible; an InsufficientCreditsError is a
    legitimate outcome when the refund won the race and is tolerated. Run several
    iterations (each a fresh user/pack on its own two connections) to raise the
    interleaving probability, asserting money invariants hold every time.
    """
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    created_users: list[UUID] = []
    try:
        for _ in range(10):
            user = _new_user(balance=500)
            pack = _pack(user.id, credits=500)
            async with Session() as s:
                async with s.begin():
                    s.add(user)
                    await s.flush()
                    s.add(pack)
            created_users.append(user.id)
            pack_id = pack.id

            async def _do_deduct(uid: UUID) -> object:
                try:
                    async with Session() as db:
                        async with db.begin():
                            await svc.deduct(db, uid, 10, reason=f"generate:{uuid4()}")
                    return None
                except InsufficientCreditsError as exc:
                    return exc  # legitimate: the refund drained the balance first

            async def _do_refund(pid: UUID) -> object:
                async with Session() as db:
                    async with db.begin():
                        source = await db.get(BillingCreditPack, pid)
                        await svc.apply_refund_reversal(
                            db,
                            source_pack=source,
                            # Half the order → ~50% proportional revoke.
                            provider_refunded_amount_cents=450,
                            full_or_fraud=False,
                            reason_label="refund",
                        )
                return None

            results = await asyncio.gather(
                _do_deduct(user.id),
                _do_refund(pack_id),
                return_exceptions=True,
            )

            deadlocks = [r for r in results if _is_deadlock(r)]
            assert not deadlocks, f"deduct↔refund deadlocked: {deadlocks}"
            # Any non-deadlock raise other than the tolerated insufficient-credits
            # is a real failure.
            unexpected = [
                r
                for r in results
                if isinstance(r, BaseException)
                and not isinstance(r, InsufficientCreditsError)
            ]
            assert not unexpected, f"unexpected error in race: {unexpected}"

            await _assert_user_consistent(Session, user.id)
    finally:
        await _cleanup_users(Session, created_users)
        await redis.aclose()
        await engine.dispose()


async def test_spend_then_reversal_creates_debt_then_repurchase_recovers_first() -> (
    None
):
    """Full reversal-then-recovery lifecycle, asserted as one conserved story.

    purchase (a pack) → spend most of it (deduct) → a full reversal of the pack:
    only the still-held remainder can be clawed back immediately, the already-spent
    portion becomes recoverable ``billing_credit_debts`` (never reclaimed from
    expired/spent balance below zero) → a fresh purchase repays that debt BEFORE any
    usable surplus is granted.
    """
    engine, Session, redis = await _setup()
    svc = CreditService(redis_client=redis)
    user = _new_user(balance=200)
    try:
        pack = _pack(user.id, credits=200)
        async with Session() as s:
            async with s.begin():
                s.add(user)
                await s.flush()
                s.add(pack)
        pack_id = pack.id

        # Spend 150 of the 200 → 50 remaining, balance 50.
        async with Session() as db:
            async with db.begin():
                await svc.deduct(db, user.id, 150, reason=f"generate:{uuid4()}")

        # Full reversal: revoke all 200; only 50 are still held (immediate), the
        # other 150 become recoverable debt (already spent).
        async with Session() as db:
            async with db.begin():
                source = await db.get(BillingCreditPack, pack_id)
                outcome = await svc.apply_refund_reversal(
                    db,
                    source_pack=source,
                    provider_refunded_amount_cents=900,  # full
                    full_or_fraud=True,
                    reason_label="refund",
                )
        assert outcome.applied is True
        assert outcome.immediate_revoke == 50
        assert outcome.debt_created == 150

        async with Session() as db:
            balance = int((await db.get(User, user.id)).credit_balance or 0)
            debt = (
                await db.execute(
                    select(BillingCreditDebt).where(
                        BillingCreditDebt.user_id == user.id,
                        BillingCreditDebt.status == "pending",
                    )
                )
            ).scalar_one()
        assert balance == 0  # the 50 held were clawed back, balance floored at 0
        assert debt.credits_owed == 150 and debt.credits_recovered == 0

        # A fresh 200-credit purchase repays the 150 debt first; only 50 is usable.
        new_pack = _pack(user.id, credits=200)
        reason = f"billing_purchase:lemonsqueezy:{new_pack.provider_order_id}"
        async with Session() as db:
            async with db.begin():
                db.add(new_pack)
                await db.flush()
                entry = await svc.grant_credits_with_debt_recovery(
                    db,
                    user_id=user.id,
                    pack=new_pack,
                    granted_credits=200,
                    ledger_reason=reason,
                )
        assert entry is not None

        async with Session() as db:
            user_row = await db.get(User, user.id)
            debt_row = await db.get(BillingCreditDebt, debt.id)
            new_pack_row = await db.get(BillingCreditPack, new_pack.id)
        # Debt fully recovered out of the new pack BEFORE surplus.
        assert debt_row.credits_recovered == 150 and debt_row.status == "recovered"
        assert new_pack_row.credits_debt_recovered == 150
        assert new_pack_row.credits_remaining == 50
        assert user_row.credit_balance == 50  # only the surplus is usable
        # Ledger surplus row reflects the surplus, not the gross grant.
        async with Session() as db:
            purchase = (
                await db.execute(
                    select(CreditLedger).where(CreditLedger.reason == reason)
                )
            ).scalar_one()
        assert purchase.amount == 50
    finally:
        await _cleanup_users(Session, [user.id])
        await redis.aclose()
        await engine.dispose()

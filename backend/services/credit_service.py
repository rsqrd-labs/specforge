from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_shared_redis
from models import BillingCreditDebt, BillingCreditPack, CreditLedger, User
from services.observability import (
    BILLING_CREDIT_DEBT_RECOVERED,
    BILLING_CREDITS_CONSUMED,
    BILLING_CREDITS_EXPIRED,
)

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "credits:"
_CACHE_TTL = 300  # 5 minutes
CREDIT_COSTS = {
    "generate": 10,
    "refine": 3,
    "regenerate": 10,
    "chat": 2,
    "export": 0,
}


class InsufficientCreditsError(Exception):
    pass


class CreditService:
    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis: Redis | None = redis_client

    def _redis_key(self, user_id: UUID) -> str:
        return f"{_CACHE_PREFIX}{user_id}"

    async def _get_redis(self) -> Redis:
        # Use the constructor-injected client (for tests) or the shared pool.
        # H-1 — T-177.
        if self._redis is None:
            self._redis = get_shared_redis()
        return self._redis

    async def get_balance(self, db: AsyncSession, user_id: UUID) -> int:
        # Sweep expired packs before reading balance.  This keeps the DB balance
        # authoritative and ensures the Redis cache reflects post-expiry state.
        # T-229 — lazy expiry.
        await self._expire_user_packs(db, user_id)
        redis = await self._get_redis()
        cached = await redis.get(self._redis_key(user_id))
        if cached is not None:
            return int(cached)

        user = await self._get_user(db, user_id)
        balance = int(user.credit_balance) if user is not None else 0
        await redis.set(self._redis_key(user_id), balance, ex=_CACHE_TTL)
        return balance

    async def _expire_user_packs(self, db: AsyncSession, user_id: UUID) -> None:
        """Sweep active packs whose expires_at has passed.

        Runs inside the caller's transaction — do NOT call db.commit() here.
        Uses SELECT FOR UPDATE on both the user row and the pack rows to prevent
        concurrent get_balance() calls from racing each other.

        The user row lock is acquired FIRST (same order as deduct()) to avoid
        deadlocks with concurrent deduct() calls.
        """
        now = datetime.now(timezone.utc)
        # Lock user row first (consistent lock ordering with deduct()).
        user = await self._get_user(db, user_id, lock=True)
        if user is None:
            return
        # Lock and fetch expired active packs.
        result = await db.execute(
            select(BillingCreditPack)
            .where(
                BillingCreditPack.user_id == user_id,
                BillingCreditPack.status == "active",
                BillingCreditPack.expires_at <= now,
            )
            .with_for_update()
        )
        expired_packs = result.scalars().all()
        if not expired_packs:
            return
        total_expired = sum(p.credits_remaining for p in expired_packs)
        for pack in expired_packs:
            # Move the lapsed remainder into credits_expired BEFORE zeroing it so
            # the conservation invariant (remaining + consumed + expired +
            # debt_recovered == purchased) holds across the lifecycle (T-294).
            pack.credits_expired += pack.credits_remaining
            pack.status = "expired"
            pack.credits_remaining = 0
        # Deduct expired credits from user balance (floor at 0 — defensive).
        user.credit_balance = max(0, int(user.credit_balance or 0) - total_expired)
        await db.flush()
        await self._invalidate(user_id)
        BILLING_CREDITS_EXPIRED.inc(total_expired)

    async def _drain_packs(self, db: AsyncSession, user_id: UUID, amount: int) -> None:
        """Drain credits_remaining from active packs in FIFO order.

        FIFO = soonest-expiring pack first (ORDER BY expires_at ASC).

        Called by deduct() AFTER recording the CreditLedger entry and updating
        user.credit_balance.  Pack rows must already be locked by
        _expire_user_packs() having acquired FOR UPDATE on the user row —
        use the same transaction.

        FIFO = ORDER BY expires_at ASC.  Never ORDER BY expires_at DESC.
        """
        if amount <= 0:
            return
        result = await db.execute(
            select(BillingCreditPack)
            .where(
                BillingCreditPack.user_id == user_id,
                BillingCreditPack.status == "active",
            )
            .order_by(
                BillingCreditPack.expires_at.asc()
            )  # FIFO: soonest-expiring first
            .with_for_update()
        )
        packs = result.scalars().all()
        remaining = amount
        for pack in packs:
            if remaining <= 0:
                break
            drain = min(pack.credits_remaining, remaining)
            pack.credits_remaining -= drain
            # Track lifetime consumption so the conservation invariant holds and
            # refunds can compute the still-revocable amount (T-294).
            pack.credits_consumed += drain
            remaining -= drain
            if pack.credits_remaining == 0:
                pack.status = "consumed"
        await db.flush()
        BILLING_CREDITS_CONSUMED.inc(amount - remaining)

    async def _get_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        lock: bool = False,
    ) -> User | None:
        statement = select(User).where(User.id == user_id)
        if lock:
            statement = statement.with_for_update()
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def credit(
        self,
        db: AsyncSession,
        user_id: UUID,
        amount: int,
        reason: str,
        metadata: dict | None = None,
    ) -> CreditLedger:
        user = await self._get_user(db, user_id, lock=True)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        user.credit_balance = int(user.credit_balance or 0) + amount
        entry = CreditLedger(
            user_id=user_id, amount=amount, reason=reason, metadata_=metadata
        )
        db.add(entry)
        await db.flush()
        await self._invalidate(user_id)
        return entry

    async def grant_credits_with_debt_recovery(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        pack: BillingCreditPack,
        granted_credits: int,
        ledger_reason: str,
    ) -> CreditLedger | None:
        """Apply a positive billing grant, repaying pending debt before usable balance.

        The single grant path for every positive billing credit (purchase — T-299,
        admin correction — T-302). ``pack`` is the freshly-created, in-session
        ``BillingCreditPack`` for this order (``credits_remaining == granted_credits``);
        ``ledger_reason`` is the order's idempotency reason
        (``billing_purchase:…`` / ``admin_billing_correction:…``).

        Debt-first (Plan §25 DC5): any pending ``billing_credit_debts`` (a shortfall
        from an earlier reversal the user had already spent) is settled oldest-first
        out of the new pack BEFORE the user sees usable credits. Each settled slice
        moves ``take`` credits from ``pack.credits_remaining`` into
        ``pack.credits_debt_recovered`` and ``debt.credits_recovered`` (so the
        conservation invariant ``remaining + consumed + expired + debt_recovered ==
        purchased`` is preserved) and writes a zero-amount audit ledger row
        ``debt_recovery:billing:{debt_id}:{pack_id}``. Only the surplus
        (``granted_credits - total_recovered``) increases ``user.credit_balance`` and
        is recorded by the single ``ledger_reason`` row (amount may be 0).

        Lock order is the canonical user → (debts) so it never deadlocks with
        deduct/expire (which lock user → packs). The whole mutation set is wrapped in
        a SAVEPOINT: a duplicate grant (same order) collides on the ledger-reason
        unique index and is rolled back to an idempotent no-op, leaving the caller's
        outer transaction intact (mirrors ``refund()``).

        Returns the surplus ``CreditLedger`` row, or ``None`` if the grant was a
        duplicate (already applied). The caller commits and then calls
        ``invalidate(user_id)``.
        """
        # Lock the user row first (canonical order shared with deduct/expire).
        user = await self._get_user(db, user_id, lock=True)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        # Lock pending debts oldest-first so concurrent grants settle deterministically.
        debts_result = await db.execute(
            select(BillingCreditDebt)
            .where(
                BillingCreditDebt.user_id == user_id,
                BillingCreditDebt.status == "pending",
            )
            .order_by(BillingCreditDebt.created_at.asc())
            .with_for_update()
        )
        pending_debts = debts_result.scalars().all()

        surplus_entry = CreditLedger(
            user_id=user_id,
            amount=0,  # finalised below once total_recovered is known
            reason=ledger_reason,
        )
        recovered_slices: list[tuple[BillingCreditDebt, int]] = []
        try:
            async with db.begin_nested():
                grant_left = granted_credits
                total_recovered = 0
                for debt in pending_debts:
                    if grant_left <= 0:
                        break
                    outstanding = debt.credits_owed - debt.credits_recovered
                    take = min(grant_left, outstanding)
                    if take <= 0:
                        continue
                    pack.credits_remaining -= take
                    pack.credits_debt_recovered += take
                    debt.credits_recovered += take
                    if debt.credits_recovered >= debt.credits_owed:
                        debt.status = "recovered"
                    debt.updated_at = datetime.now(timezone.utc)
                    db.add(
                        CreditLedger(
                            user_id=user_id,
                            amount=0,
                            reason=f"debt_recovery:billing:{debt.id}:{pack.id}",
                        )
                    )
                    recovered_slices.append((debt, take))
                    grant_left -= take
                    total_recovered += take

                surplus = granted_credits - total_recovered
                surplus_entry.amount = surplus
                user.credit_balance = int(user.credit_balance or 0) + surplus
                db.add(surplus_entry)
                await db.flush()
        except IntegrityError:
            # The ledger-reason unique index rejected a duplicate grant for this
            # order; the SAVEPOINT rolled back every mutation above (pack/debt/
            # balance + ledger rows), leaving the outer transaction intact. Treat
            # as idempotent — the credits were already granted.
            logger.warning(
                "credit.grant.duplicate user_id=%s reason=%s",
                user_id,
                ledger_reason,
            )
            return None

        for _debt, take in recovered_slices:
            BILLING_CREDIT_DEBT_RECOVERED.inc(take)
        await self._invalidate(user_id)
        return surplus_entry

    async def deduct(
        self,
        db: AsyncSession,
        user_id: UUID,
        amount: int,
        reason: str,
    ) -> CreditLedger:
        await self._expire_user_packs(db, user_id)  # Step 1: sweep expired packs
        user = await self._get_user(db, user_id, lock=True)
        balance = int(user.credit_balance or 0) if user is not None else 0
        if user is None or balance < amount:
            raise InsufficientCreditsError(
                f"Balance {balance} is less than required {amount}"
            )
        user.credit_balance = balance - amount
        entry = CreditLedger(user_id=user_id, amount=-amount, reason=reason)
        db.add(entry)
        await db.flush()
        await self._drain_packs(db, user_id, amount)  # Step 2: FIFO pack drain
        await self._invalidate(user_id)
        return entry

    async def refund(
        self,
        db: AsyncSession,
        ledger_entry_id: UUID,
        user_id: UUID | None = None,
    ) -> None:
        original = await self._get_ledger_entry(db, ledger_entry_id)
        if original is None:
            logger.error(
                "credit.refund.missing_entry ledger_entry_id=%s user_id=%s",
                ledger_entry_id,
                user_id,
            )
            return
        if original.amount >= 0:
            logger.error(
                "credit.refund.not_a_deduction ledger_entry_id=%s amount=%d user_id=%s",
                ledger_entry_id,
                original.amount,
                original.user_id,
            )
            return
        if user_id is not None and original.user_id != user_id:
            logger.error(
                "credit.refund.user_mismatch ledger_entry_id=%s "
                "expected_user_id=%s actual_user_id=%s",
                ledger_entry_id,
                user_id,
                original.user_id,
            )
            return

        refund_reason = f"refund:{ledger_entry_id}"
        existing_refund = await self._get_refund_entry(
            db,
            original.user_id,
            refund_reason,
        )
        if existing_refund is not None:
            return

        user = await self._get_user(db, original.user_id, lock=True)
        if user is None:
            logger.error(
                "credit.refund.user_missing ledger_entry_id=%s user_id=%s",
                ledger_entry_id,
                original.user_id,
            )
            return

        refund_amount = abs(original.amount)
        refund_entry = CreditLedger(
            user_id=original.user_id,
            amount=refund_amount,
            reason=refund_reason,
        )
        try:
            async with db.begin_nested():
                # Scope the INSERT to a SAVEPOINT so that a concurrent duplicate
                # refund (IntegrityError on the unique reason constraint) only
                # rolls back this savepoint — the outer transaction (stage status
                # updates, content writes, etc.) remains intact.  MF-3 — T-207.
                db.add(refund_entry)
                await db.flush()
        except IntegrityError:
            # A concurrent refund for the same deduction already committed.
            # The SAVEPOINT was automatically rolled back; the outer transaction
            # is intact.  Treat as idempotent — the credits were already refunded.
            logger.warning(
                "credit.refund.duplicate_entry ledger_entry_id=%s user_id=%s",
                ledger_entry_id,
                original.user_id,
            )
            return
        user.credit_balance = int(user.credit_balance or 0) + refund_amount
        await db.flush()
        await self._invalidate(original.user_id)

    async def _get_ledger_entry(
        self,
        db: AsyncSession,
        ledger_entry_id: UUID,
    ) -> CreditLedger | None:
        result = await db.execute(
            select(CreditLedger).where(CreditLedger.id == ledger_entry_id)
        )
        return result.scalar_one_or_none()

    async def _get_refund_entry(
        self,
        db: AsyncSession,
        user_id: UUID,
        refund_reason: str,
    ) -> CreditLedger | None:
        result = await db.execute(
            select(CreditLedger).where(
                CreditLedger.user_id == user_id,
                CreditLedger.reason == refund_reason,
            )
        )
        return result.scalar_one_or_none()

    async def _invalidate(self, user_id: UUID) -> None:
        redis = await self._get_redis()
        try:
            await redis.delete(self._redis_key(user_id))
        except RedisError:
            logger.warning(
                "credit.cache_invalidation_failed user_id=%s",
                user_id,
                exc_info=True,
            )
        # Also flush the shared auth middleware cache so the next request — on
        # ANY worker — reflects the updated credit_balance immediately rather
        # than serving a stale entry. The cache is Redis-backed, so this
        # invalidation propagates cross-worker (LF-1, was H-4 — T-180).
        # Lazy import to avoid a circular dependency:
        #   auth_service → credit_service → middleware.auth → auth_service.
        from middleware.auth import invalidate_user_cache  # noqa: PLC0415

        await invalidate_user_cache(user_id)

    async def invalidate(self, user_id: UUID) -> None:
        """Public alias for post-commit cache invalidation.

        Call this immediately after ``db.commit()`` in any code path that
        first called ``deduct()``, ``credit()``, or ``refund()``.  The first
        invalidation (inside those methods, after flush) clears the cache
        eagerly.  This second call ensures any concurrent ``get_balance()``
        that re-populated the cache during the flush→commit window is
        immediately evicted after the true balance is committed.  H-2 — T-219.
        """
        await self._invalidate(user_id)


credit_service = CreditService()

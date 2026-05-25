from __future__ import annotations

import logging
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_shared_redis
from models import CreditLedger, User

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
        redis = await self._get_redis()
        cached = await redis.get(self._redis_key(user_id))
        if cached is not None:
            return int(cached)

        user = await self._get_user(db, user_id)
        balance = int(user.credit_balance) if user is not None else 0
        await redis.set(self._redis_key(user_id), balance, ex=_CACHE_TTL)
        return balance

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

    async def deduct(
        self,
        db: AsyncSession,
        user_id: UUID,
        amount: int,
        reason: str,
    ) -> CreditLedger:
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
        # Also flush the in-process auth middleware cache so the next request
        # reflects the updated credit_balance immediately rather than serving
        # the 30-second stale entry.  H-4 — T-180.
        # Lazy import to avoid a circular dependency:
        #   auth_service → credit_service → middleware.auth → auth_service.
        from middleware.auth import invalidate_user_cache  # noqa: PLC0415

        invalidate_user_cache(user_id)

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

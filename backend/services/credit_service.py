from __future__ import annotations

import logging
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
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
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
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
        result = await db.execute(
            select(CreditLedger).where(CreditLedger.id == ledger_entry_id)
        )
        original = result.scalar_one_or_none()
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
        execute = getattr(db, "execute")
        existing_result = await execute(
            select(CreditLedger).where(
                CreditLedger.user_id == original.user_id,
                CreditLedger.reason == refund_reason,
            )
        )
        existing_refund = existing_result.scalar_one_or_none()
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
        user.credit_balance = int(user.credit_balance or 0) + refund_amount
        refund_entry = CreditLedger(
            user_id=original.user_id,
            amount=refund_amount,
            reason=refund_reason,
        )
        db.add(refund_entry)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return
        await self._invalidate(original.user_id)

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


credit_service = CreditService()

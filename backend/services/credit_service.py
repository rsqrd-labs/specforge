from __future__ import annotations

import logging
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import CreditLedger

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "credits:"
_CACHE_TTL = 300  # 5 minutes


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

        result = await db.execute(
            select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
                CreditLedger.user_id == user_id
            )
        )
        balance = int(result.scalar_one())
        await redis.set(self._redis_key(user_id), balance, ex=_CACHE_TTL)
        return balance

    async def credit(
        self,
        db: AsyncSession,
        user_id: UUID,
        amount: int,
        reason: str,
        metadata: dict | None = None,
    ) -> CreditLedger:
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
        # Lock rows individually — SELECT SUM(...) FOR UPDATE is invalid in PostgreSQL
        result = await db.execute(
            select(CreditLedger)
            .where(CreditLedger.user_id == user_id)
            .with_for_update()
        )
        rows = result.scalars().all()
        balance = sum(r.amount for r in rows)
        if balance < amount:
            raise InsufficientCreditsError(
                f"Balance {balance} is less than required {amount}"
            )
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
        refund_entry = CreditLedger(
            user_id=original.user_id,
            amount=abs(original.amount),
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
        await redis.delete(self._redis_key(user_id))


credit_service = CreditService()

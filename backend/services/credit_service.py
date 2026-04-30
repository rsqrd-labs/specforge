from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CreditLedger


class CreditService:
    async def get_balance(self, db: AsyncSession, user_id: UUID) -> int:
        result = await db.execute(
            select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
                CreditLedger.user_id == user_id
            )
        )
        return result.scalar_one()

    async def credit(
        self,
        db: AsyncSession,
        user_id: UUID,
        amount: int,
        reason: str,
    ) -> CreditLedger:
        entry = CreditLedger(user_id=user_id, amount=amount, reason=reason)
        db.add(entry)
        await db.flush()
        return entry


credit_service = CreditService()

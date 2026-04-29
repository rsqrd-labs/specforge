from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models import CreditLedger


class CreditService:
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

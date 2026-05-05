from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from models import User
from services.credit_service import credit_service


def require_credits(amount: int):
    async def check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        # Optimistic pre-check for fast UX rejection (TOCTOU). The actual
        # balance is enforced atomically by SELECT FOR UPDATE inside deduct().
        balance = await credit_service.get_balance(db, user.id)
        if balance < amount:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "insufficient_credits",
                    "balance": balance,
                    "required": amount,
                },
            )

    return check

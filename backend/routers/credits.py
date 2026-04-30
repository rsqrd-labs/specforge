from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from models import CreditLedger, User
from schemas.credits import CreditBalance, CreditLedgerEntry
from services.credit_service import credit_service

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("/balance", response_model=CreditBalance)
async def get_balance(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreditBalance:
    balance = await credit_service.get_balance(db, user.id)
    return CreditBalance(balance=balance)


@router.get("/history", response_model=list[CreditLedgerEntry])
async def get_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CreditLedgerEntry]:
    result = await db.execute(
        select(CreditLedger)
        .where(CreditLedger.user_id == user.id)
        .order_by(desc(CreditLedger.created_at))
        .limit(limit)
        .offset(offset)
    )
    return [CreditLedgerEntry.model_validate(entry) for entry in result.scalars()]

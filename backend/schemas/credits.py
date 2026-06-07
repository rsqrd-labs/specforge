from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreditBalance(BaseModel):
    balance: int = Field(ge=0)
    generation_cost: int = Field(ge=0)
    # Unrecovered payment-reversal debt (Phase 22 — T-305): the sum of pending
    # billing_credit_debts (credits_owed − credits_recovered) for the user. Surfaced
    # separately so the UI can show it as a distinct note and NEVER fold it into the
    # usable balance. Defaults to 0 when the user has no pending reversal debt.
    billing_debt_credits: int = Field(default=0, ge=0)

    model_config = ConfigDict(from_attributes=True)


class CreditLedgerEntry(BaseModel):
    id: UUID
    amount: int
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

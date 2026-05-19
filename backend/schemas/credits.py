from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreditBalance(BaseModel):
    balance: int = Field(ge=0)
    generation_cost: int = Field(ge=0)

    model_config = ConfigDict(from_attributes=True)


class CreditLedgerEntry(BaseModel):
    id: UUID
    amount: int
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

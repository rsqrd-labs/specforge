from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str | None
    avatar_url: str | None
    credit_balance: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

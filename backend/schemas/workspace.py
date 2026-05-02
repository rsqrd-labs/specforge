from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.stage import StageStatus, StageType
from services.llm.provider_config import VALID_MODELS

Provider = Literal["anthropic", "openai", "google"]
WorkspaceStatus = Literal["active", "archived"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    problem_statement: str = Field(min_length=50, max_length=10_000)
    provider: Provider
    model: str = Field(min_length=1)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("model")
    @classmethod
    def model_must_be_valid(cls, v: str, info: object) -> str:
        provider = getattr(info, "data", {}).get("provider")
        if provider:
            allowed = VALID_MODELS.get(provider, set())
            if v not in allowed:
                raise ValueError(
                    f"model {v!r} is not supported for provider {provider!r}. "
                    f"Allowed: {sorted(allowed)}"
                )
        return v


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(from_attributes=True)


class StageSummary(BaseModel):
    id: UUID
    type: StageType
    status: StageStatus
    current_version: int

    model_config = ConfigDict(from_attributes=True)


class WorkspaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    problem_statement: str
    provider: Provider
    model: str
    status: WorkspaceStatus
    stages: list[StageSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

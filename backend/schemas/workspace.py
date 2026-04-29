from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.stage import StageStatus, StageType

Provider = Literal["anthropic", "openai", "google"]
WorkspaceStatus = Literal["active", "archived"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    problem_statement: str = Field(min_length=50, max_length=10_000)
    provider: Provider
    model: str = Field(min_length=1)

    model_config = ConfigDict(from_attributes=True)


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

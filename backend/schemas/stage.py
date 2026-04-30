from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StageType = Literal["spec", "plan", "harness", "tasks"]
StageStatus = Literal["locked", "draft", "in_progress", "finalised", "stale"]


class GenerateRequest(BaseModel):
    stage_id: UUID

    model_config = ConfigDict(from_attributes=True)


class RefineRequest(BaseModel):
    instruction: str = Field(min_length=1)
    selection_start: int = Field(ge=0)
    selection_end: int = Field(ge=0)
    selected_text: str = Field(min_length=1)

    model_config = ConfigDict(from_attributes=True)


class EvalResponse(BaseModel):
    id: UUID
    stage_version_id: UUID
    stage_type: StageType
    overall_score: int | None = Field(default=None, ge=0, le=100)
    completeness: int | None = Field(default=None, ge=0, le=100)
    clarity: int | None = Field(default=None, ge=0, le=100)
    coverage_percent: int | None = Field(default=None, ge=0, le=100)
    uncovered_reqs: list[str] | None = None
    tasks_without_ref: list[dict[str, Any]] | None = None
    flagged: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StageResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    type: StageType
    content: str | None
    status: StageStatus
    current_version: int
    eval_result: EvalResponse | None = None
    finalised_at: datetime | None = None
    review_gate_acknowledged: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StageVersionResponse(BaseModel):
    id: UUID
    stage_id: UUID
    version: int
    content: str
    created_by: Literal["user", "ai"]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiffResponse(BaseModel):
    diff: str
    original: str
    proposed: str
    large_selection: bool = False

    model_config = ConfigDict(from_attributes=True)


class AcceptDiffRequest(BaseModel):
    proposed_content: str

    model_config = ConfigDict(from_attributes=True)


class RollbackRequest(BaseModel):
    version_number: int = Field(ge=1)

    model_config = ConfigDict(from_attributes=True)

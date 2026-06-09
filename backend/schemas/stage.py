from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

StageType = Literal["spec", "plan", "harness", "tasks"]
StageStatus = Literal["locked", "draft", "in_progress", "finalised", "stale"]
QualityGateStatus = Literal["clear", "blocked", "overridden"]


class GenerateRequest(BaseModel):
    stage_id: UUID

    model_config = ConfigDict(from_attributes=True)


class RefineRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)
    selection_start: int = Field(ge=0)
    selection_end: int = Field(ge=0)
    selected_text: str = Field(min_length=1, max_length=100_000)
    mode: Literal["focused", "section", "full"] = "focused"

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def selection_end_must_not_precede_start(self) -> "RefineRequest":
        if self.selection_end < self.selection_start:
            raise ValueError(
                "selection_end must be greater than or equal to selection_start"
            )
        return self


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


class StageQualityGate(BaseModel):
    status: QualityGateStatus
    stage: StageType
    kind: str | None = None
    findings: list[dict[str, Any]] | None = None
    missing: list[str] | None = None
    version: int | None = None
    failed_at: datetime | None = None

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
    gap_patch_used: bool = False
    quality_gate: StageQualityGate | None = None
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


_MAX_CONTENT_LENGTH = 500_000  # ~500 KB; prevents memory-exhaustion DoS


class AcceptDiffRequest(BaseModel):
    proposed_content: str = Field(max_length=_MAX_CONTENT_LENGTH)

    model_config = ConfigDict(from_attributes=True)


class RollbackRequest(BaseModel):
    version_number: int = Field(ge=1)

    model_config = ConfigDict(from_attributes=True)


class ContentEditRequest(BaseModel):
    content: str = Field(max_length=_MAX_CONTENT_LENGTH)

    model_config = ConfigDict(from_attributes=True)

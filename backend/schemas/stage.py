from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

StageType = Literal["spec", "plan", "harness", "tasks"]
StageStatus = Literal["locked", "draft", "in_progress", "finalised", "stale"]
# "advisory" (issue #34) is a delivered, finalisable draft carrying non-blocking
# findings — the status the post-`done` refetch (GET /stages/{id} → StageResponse)
# must serialize for AdvisoryFindingsPanel to render. Omitting it 500s the refetch
# for every advisory stage (critic suggestions and the Phase-D condensed notice).
QualityGateStatus = Literal["clear", "blocked", "overridden", "advisory"]


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


class GenerationEstimate(BaseModel):
    """One aggregate latency band for a (provider, stage, operation) — issue #21
    Phase 2b. Durations in seconds; ``n`` is the sample count behind them.

    Aggregate-only: no user, workspace, or content field ever appears here.
    """

    stage: StageType
    operation: Literal["generate", "focused-patch", "regenerate-gaps"]
    p50: int = Field(ge=0)
    p90: int = Field(ge=0)
    n: int = Field(ge=0)

    model_config = ConfigDict(from_attributes=True)


class GenerationEstimatesResponse(BaseModel):
    """Cached generation-ETA rollup. Empty ``estimates`` (cache miss / disabled /
    low sample volume) is a valid response — the client falls back to its
    constant heuristic table."""

    estimates: list[GenerationEstimate] = Field(default_factory=list)
    generated_at: datetime | None = None

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


class StageQualityGateRecovery(BaseModel):
    """Derived, billing-honest recovery contract for a blocked quality gate.

    Built by ``models.stage.derive_quality_gate_recovery`` and attached to a
    blocked stage's ``quality_gate`` so the frontend has one authoritative source
    for the recovery action, override availability, retry cost, refund truth, and
    the user-facing message.
    """

    action: str
    overridable: bool
    credit_required: int
    refunded_prior_attempt: bool
    message: str

    model_config = ConfigDict(from_attributes=True)


class StageQualityGate(BaseModel):
    status: QualityGateStatus
    stage: StageType
    kind: str | None = None
    findings: list[dict[str, Any]] | None = None
    missing: list[str] | None = None
    reasons: list[dict[str, Any]] | None = None
    override_allowed: bool | None = None
    repair_attempted: bool | None = None
    policy_version: str | None = None
    verified_at: datetime | None = None
    sources: list[str] | None = None
    version: int | None = None
    failed_at: datetime | None = None
    recovery: StageQualityGateRecovery | None = None

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
    # Honest elapsed baseline for the streaming overlay (RC-1) + reconnect
    # operation label (A6). Both nullable/additive — old rows serialize None and
    # the frontend falls back to updated_at. Nested identically into the
    # workspace load (schemas.workspace), so a post-refresh reconnect sees them.
    generation_started_at: datetime | None = None
    generation_action: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ResearchSourceResponse(BaseModel):
    """One provenance entry for a grounded version (issue #12, Phase 4).

    URL is allowlisted to http/https at assembly time on the backend, so the
    frontend can render it as a link without re-validating; title is already
    sanitised."""

    url: str
    title: str = ""

    model_config = ConfigDict(from_attributes=True)


class StageVersionResponse(BaseModel):
    id: UUID
    stage_id: UUID
    version: int
    content: str
    created_by: Literal["user", "ai"]
    created_at: datetime
    # Brave web-research provenance (issue #12, Phase 4). Both None unless this
    # version was generated with grounding injected; research_context present is
    # the authoritative "used web research" signal for the version view.
    research_context: str | None = None
    research_sources: list[ResearchSourceResponse] | None = None

    model_config = ConfigDict(from_attributes=True)


class DiffResponse(BaseModel):
    diff: str
    original: str
    proposed: str
    # Optimistic-concurrency token. Accepting the proposal is valid only while
    # the stage still points at the exact version this diff was generated from.
    base_version: int = Field(ge=0)
    large_selection: bool = False

    model_config = ConfigDict(from_attributes=True)


_MAX_CONTENT_LENGTH = 500_000  # ~500 KB; prevents memory-exhaustion DoS


class AcceptDiffRequest(BaseModel):
    proposed_content: str = Field(max_length=_MAX_CONTENT_LENGTH)
    base_version: int = Field(ge=0)

    model_config = ConfigDict(from_attributes=True)


class RollbackRequest(BaseModel):
    version_number: int = Field(ge=1)

    model_config = ConfigDict(from_attributes=True)


class ContentEditRequest(BaseModel):
    content: str = Field(max_length=_MAX_CONTENT_LENGTH)

    model_config = ConfigDict(from_attributes=True)

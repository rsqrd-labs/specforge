from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.stage import StageResponse
from services.llm.provider_config import VALID_MODELS

Provider = Literal["anthropic", "openai", "google"]
WorkspaceStatus = Literal["active", "archived"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    problem_statement: str = Field(min_length=50, max_length=10_000)
    provider: Provider
    # Deprecated public input. Concrete model routing is server-owned; this
    # optional field remains only to reject invalid legacy clients cleanly.
    model: str | None = Field(default=None, min_length=1)
    template_slug: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )

    model_config = ConfigDict(from_attributes=True)

    @field_validator("model")
    @classmethod
    def model_must_be_valid(cls, v: str | None, info: object) -> str | None:
        if v is None:
            return v
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
    name: str | None = Field(default=None, min_length=1, max_length=200)
    problem_statement: str | None = Field(
        default=None,
        min_length=50,
        max_length=10_000,
    )

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "WorkspaceUpdate":
        if self.name is None and self.problem_statement is None:
            raise ValueError("At least one workspace field must be provided")
        return self


class CoverageSummary(BaseModel):
    """Harness coverage figure surfaced from the latest EvalResult.

    Derived on the fly when assembling the workspace response (see T-172);
    nothing is persisted on the workspace row itself.
    """

    tests: int = Field(ge=0)
    covered: int = Field(ge=0)
    total: int = Field(ge=0)
    percent: int = Field(ge=0, le=100)

    model_config = ConfigDict(from_attributes=True)


class ClarificationQA(BaseModel):
    """One captured Q/A pair from the Spec Clarification step."""

    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(from_attributes=True)


class ClarifyingQuestion(BaseModel):
    """Single question returned by the clarification judge model."""

    question: str = Field(min_length=1, max_length=500)
    why_it_matters: str = Field(min_length=1, max_length=500)


class ClarifyResponse(BaseModel):
    """Successful payload from POST /workspaces/{id}/clarify.

    The route returns 204 No Content when the judge model is unavailable
    or times out, so this shape is only seen on the happy path.
    """

    questions: list[ClarifyingQuestion]


class ClarifyingAnswer(BaseModel):
    """A user-supplied answer to one of the cached round's questions."""

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=1000)


class ClarifySubmitRequest(BaseModel):
    """Payload for PATCH /workspaces/{id}/clarify.

    Every ``question`` must match (string-equal) a question from the
    workspace's most recent ``POST /clarify`` round held in Redis;
    answers whose question is not in the cached round are rejected with
    400 so a user cannot smuggle arbitrary text past the validator by
    fabricating a question. Each answer is sanitised before persistence.
    """

    answers: list[ClarifyingAnswer] = Field(min_length=1)


class WorkspaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    problem_statement: str
    provider: Provider
    model: str
    status: WorkspaceStatus
    template_slug: str | None = None
    clarification_qa: list[ClarificationQA] | None = None
    public_share_slug: str | None = None
    public_share_enabled: bool = False
    coverage_summary: CoverageSummary | None = None
    stages: list[StageResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# T-USE-09: Public share allow-list — the contract for GET /public/{slug}.
# Schema-locked to harness/schemas/public-workspace.schema.json. `extra="forbid"`
# is the privacy guard: adding any future field to this model is an explicit
# privacy decision, never a silent ORM passthrough.


class PublicStageView(BaseModel):
    type: Literal["spec", "plan", "harness", "tasks"]
    content: str

    model_config = ConfigDict(extra="forbid")


class PublicEvalSummary(BaseModel):
    overall_score: int | None = Field(default=None, ge=0, le=100)
    completeness: int | None = Field(default=None, ge=0, le=100)
    clarity: int | None = Field(default=None, ge=0, le=100)

    model_config = ConfigDict(extra="forbid")


class PublicWorkspaceResponse(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider_label: str
    stages: list[PublicStageView] = Field(min_length=4, max_length=4)
    coverage_summary: CoverageSummary | None = None
    eval_summary: PublicEvalSummary | None = None
    shared_at: datetime

    model_config = ConfigDict(extra="forbid")


class ShareLinkResponse(BaseModel):
    slug: str
    url: str
    enabled: bool

    model_config = ConfigDict(extra="forbid")

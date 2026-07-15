from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.stage import StageResponse
from services.llm.provider_config import VALID_MODELS
from services.security.problem_statement_gate import (
    PROBLEM_STATEMENT_MAX_CHARS,
    PROBLEM_STATEMENT_MIN_CHARS,
)

Provider = Literal["anthropic", "openai", "google"]
WorkspaceStatus = Literal["active", "archived"]
# Demo Day mode (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md). A generation profile
# chosen at creation; default 'standard' keeps the existing path byte-identical.
WorkspaceMode = Literal["standard", "demo_day"]
TargetAgent = Literal["claude_code", "codex", "both"]
# Soft upper bound on the advisory build-time target (24h). Rejects absurd input
# at the boundary; the linter's default is 300 (5h) when unset.
_TIME_BUDGET_MAX_MINUTES = 24 * 60


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    problem_statement: str = Field(
        min_length=PROBLEM_STATEMENT_MIN_CHARS,
        max_length=PROBLEM_STATEMENT_MAX_CHARS,
    )
    provider: Provider
    # Deprecated public input. Concrete model routing is server-owned; this
    # optional field remains only to reject invalid legacy clients cleanly.
    model: str | None = Field(default=None, min_length=1)
    template_slug: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    # Demo Day mode fields. All default to the standard-mode values so a client
    # that omits them produces a byte-identical create request to today (§4).
    mode: WorkspaceMode = "standard"
    target_agent: TargetAgent | None = None
    time_budget_minutes: int | None = Field(
        default=None,
        gt=0,
        le=_TIME_BUDGET_MAX_MINUTES,
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

    @model_validator(mode="after")
    def _validate_demo_day_fields(self) -> "WorkspaceCreate":
        if self.mode == "demo_day":
            # The construction guarantee requires a test-executing agent; the
            # agent choice is therefore mandatory for a demo_day workspace.
            if self.target_agent is None:
                raise ValueError(
                    "target_agent is required when mode is 'demo_day' "
                    "(one of: claude_code, codex, both)"
                )
        else:
            # The agent-instruction target applies to both workspace modes.
            # Only the construction time budget remains Demo-Day-specific.
            self.time_budget_minutes = None
        return self


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    problem_statement: str | None = Field(
        default=None,
        min_length=PROBLEM_STATEMENT_MIN_CHARS,
        max_length=PROBLEM_STATEMENT_MAX_CHARS,
    )
    target_agent: TargetAgent | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "WorkspaceUpdate":
        if (
            self.name is None
            and self.problem_statement is None
            and self.target_agent is None
        ):
            raise ValueError("At least one workspace field must be provided")
        return self


class WorkspaceCriticToggle(BaseModel):
    """Owner-only toggle for the Phase 19 critic quality gate (T-247).

    Setting disable_critic=True bypasses the critic second-pass for the
    workspace; the router writes a `critic_disabled` audit log row.
    """

    disable_critic: bool

    model_config = ConfigDict(from_attributes=True)


class WorkspaceResearchToggle(BaseModel):
    """Owner-only opt-in toggle for Brave web-research enrichment (issue #12).

    Setting brave_research_enabled=True permits generation for this workspace to
    send the idea text to Brave (a third party) for up-to-date web grounding,
    at a per-generation credit cost. Off by default; the router writes a
    `brave_research_toggled` audit log row. Enrichment always degrades to
    no-research on failure, so this flag never affects whether generation runs.
    """

    brave_research_enabled: bool

    model_config = ConfigDict(from_attributes=True)


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

    ``mode="round"`` is the original first-time flow: every ``question`` must
    match (string-equal) a question from the workspace's most recent
    ``POST /clarify`` round held in Redis.

    ``mode="existing"`` is the retry/edit flow after answers already exist on
    the workspace: every ``question`` must match a saved clarification question
    on that owned workspace. This avoids another judge-model clarification call
    while still rejecting fabricated questions. Each answer is sanitised before
    persistence in both modes.
    """

    answers: list[ClarifyingAnswer] = Field(min_length=1)
    mode: Literal["round", "existing"] = "round"


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
    disable_critic: bool = False
    brave_research_enabled: bool = False
    mode: WorkspaceMode = "standard"
    target_agent: TargetAgent | None = None
    time_budget_minutes: int | None = None
    # The persisted construction verdict (Demo Day mode, plan §7.2). NULL for a
    # standard workspace and until the verifier first runs; the shape is
    # ``ConstructionVerdict.to_dict()``. Passed through as an opaque dict — the
    # frontend badge/panel render it — so a future verdict-field addition needs no
    # schema churn here. The column auto-populates via ``from_attributes``.
    construction_verdict: dict | None = None
    coverage_summary: CoverageSummary | None = None
    stages: list[StageResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("mode", mode="before")
    @classmethod
    def _default_mode(cls, v: object) -> object:
        # A NOT NULL DB column with server_default 'standard' is never NULL on a
        # persisted row, but an in-memory ORM object built without a flush (tests)
        # has mode=None. Coerce to the standard default so serialisation never
        # 500s on such rows.
        return "standard" if v is None else v


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


class TrashedWorkspaceResponse(BaseModel):
    """A trashed (archived) workspace for the "Recently deleted" surface (#43).

    ``purge_after`` is the computed hard-delete date (``archived_at`` + the
    applicable retention window: the short acked window when the delete recorded
    an acknowledgment, the conservative legacy window otherwise). The client shows
    the countdown + Restore + Export until then.
    """

    id: UUID
    name: str
    provider: Provider
    archived_at: datetime
    purge_after: datetime
    acknowledged: bool

    model_config = ConfigDict(extra="forbid")

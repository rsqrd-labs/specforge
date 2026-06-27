from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID as PythonUUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base
from services.security.problem_statement_gate import (
    PROBLEM_STATEMENT_MAX_CHARS,
    PROBLEM_STATEMENT_MIN_CHARS,
)

if TYPE_CHECKING:
    from models.stage import Stage
    from models.user import User


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_workspaces_status",
        ),
        CheckConstraint("char_length(name) <= 200", name="ck_workspaces_name_len"),
        # Floor + ceiling mirror problem_statement_gate (the semantic authority);
        # migration 0026 carries the same literals as the live DB constraint.
        CheckConstraint(
            "char_length(problem_statement) BETWEEN "
            f"{PROBLEM_STATEMENT_MIN_CHARS} AND {PROBLEM_STATEMENT_MAX_CHARS}",
            name="ck_workspaces_problem_statement_len",
        ),
        # Demo Day mode (Phase 0). Literals mirror migration 0029 and the
        # WorkspaceCreate enum validator (schemas/workspace.py).
        CheckConstraint(
            "mode IN ('standard', 'demo_day')",
            name="ck_workspaces_mode",
        ),
        CheckConstraint(
            "target_agent IS NULL OR target_agent IN ('claude_code', 'codex')",
            name="ck_workspaces_target_agent",
        ),
        CheckConstraint(
            "time_budget_minutes IS NULL OR time_budget_minutes > 0",
            name="ck_workspaces_time_budget_minutes",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=text("'active'"),
    )
    template_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_qa: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    public_share_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_share_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    public_shared_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    # Owner-only escape hatch for the Phase 19 critic quality gate (T-247).
    # Toggling it writes a structured `critic_disabled` audit log row.
    disable_critic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    # Per-workspace opt-in for Brave web-research enrichment (issue #12, Phase 3).
    # Default OFF — sending the idea text to Brave is a third-party data egress and
    # a credit charge, so it is strictly opt-in and never inferred. Toggling it
    # writes a structured `brave_research_toggled` audit log row. Even when on,
    # generation degrades to no-research on any failure/insufficient-credit path,
    # so this flag controls *whether we may*, never *whether generation can run*.
    brave_research_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    # Demo Day mode (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md). A generation
    # profile chosen at creation and workspace-scoped (like `provider`), not a
    # per-stage toggle: the four stages must be mutually coherent. Default
    # 'standard' so every existing/standard workspace takes the unchanged code
    # path everywhere (the §4 byte-identical regression-pin contract).
    mode: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="standard",
        server_default=text("'standard'"),
    )
    # The coding agent the export's operating manual is tuned for. NULL for
    # standard workspaces; required (claude_code | codex) for demo_day. Selects
    # the manual filename/idiom (CLAUDE.md vs AGENTS.md) and nothing else
    # structural.
    target_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Advisory build-time target in minutes for a demo_day package. Nullable;
    # the construction verifier falls back to 300 (5h) when NULL. Never certified
    # — it exists to force scope down, not as a guarantee (plan §2.2).
    time_budget_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The persisted construction verdict (plan §7.2 / §11.3). The verifier is
    # workspace-level — it spans all four stage versions — so its verdict lives on
    # the workspace row as nullable JSONB rather than per-stage. NULL until the
    # verifier first runs (after the tasks stage exists for a demo_day workspace);
    # always NULL for a standard workspace. The shape is
    # ``ConstructionVerdict.to_dict()`` (verified / checks / estimated_minutes /
    # time_budget_minutes / stage_versions / regen_attempted); the stamped
    # ``stage_versions`` carry the staleness signal so no extra column is needed.
    construction_verdict: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="workspaces")
    stages: Mapped[list["Stage"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )

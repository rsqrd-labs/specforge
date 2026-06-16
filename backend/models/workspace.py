from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID as PythonUUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

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
        CheckConstraint(
            "char_length(problem_statement) BETWEEN 50 AND 10000",
            name="ck_workspaces_problem_statement_len",
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

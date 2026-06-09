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

if TYPE_CHECKING:
    from models.stage_version import StageVersion
    from models.workspace import Workspace


class Stage(Base):
    __tablename__ = "stages"
    __table_args__ = (
        CheckConstraint(
            "type IN ('spec', 'plan', 'harness', 'tasks')",
            name="ck_stages_type",
        ),
        CheckConstraint(
            "status IN ('locked', 'draft', 'in_progress', 'finalised', 'stale')",
            name="ck_stages_status",
        ),
        CheckConstraint(
            "quality_gate_status IN ('clear', 'blocked', 'overridden')",
            name="ck_stages_quality_gate_status",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    workspace_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False)
    current_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    finalised_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    review_gate_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    gap_patch_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    quality_gate_status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="clear",
        server_default=text("'clear'"),
    )
    quality_gate_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_gate_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality_gate_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_gate_failed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
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
    deduction_ledger_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credit_ledger.id", ondelete="SET NULL"),
        nullable=True,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="stages")
    versions: Mapped[list["StageVersion"]] = relationship(
        back_populates="stage",
        cascade="all, delete-orphan",
    )

    @property
    def quality_gate(self) -> dict | None:
        status = self.quality_gate_status or "clear"
        if status == "clear":
            return None

        payload = dict(self.quality_gate_payload or {})
        payload.setdefault("stage", self.type)
        payload.setdefault("kind", self.quality_gate_kind)
        payload["status"] = status
        payload["version"] = self.quality_gate_version
        payload["failed_at"] = (
            self.quality_gate_failed_at.isoformat()
            if self.quality_gate_failed_at is not None
            else None
        )
        return payload

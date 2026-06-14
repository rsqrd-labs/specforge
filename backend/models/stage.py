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


# Quality-gate kinds whose block can only be cleared by regenerating — an
# override is refused for them. This mirrors StageManager.override_quality_gate,
# which rejects override for exactly these two kinds; missing_sections and
# critic_findings stay overridable. Kept as literals here (not imported from
# services) so the models layer never depends upward on services; a guard test
# (test_stage_manager.py) asserts this set stays in lockstep with
# override_quality_gate so the two can never silently drift.
NON_OVERRIDABLE_GATE_KINDS: frozenset[str] = frozenset(
    {"incomplete_output", "technology_safety"}
)

# Credits charged for a (re)generation. Mirrors require_credits(10) on the
# generate/regenerate routes; surfaced in the recovery contract so the UI can
# tell the user exactly what a retry costs.
GENERATION_CREDIT_COST = 10


def _recovery_message(kind: str | None, *, overridable: bool, refunded: bool) -> str:
    """Build the kind-specific, billing-honest recovery sentence shown to users."""
    refund_clause = " Your previous attempt was refunded." if refunded else ""
    if kind == "incomplete_output":
        return (
            "This version stopped before it was complete and can't be finalised. "
            "Regenerate to produce a full version." + refund_clause
        )
    if kind == "technology_safety":
        return (
            "This version proposes unsafe technology choices and can't be "
            "finalised. Regenerate to continue." + refund_clause
        )
    if kind == "missing_sections":
        return (
            "This version is missing required sections. Regenerate, or override "
            "to finalise it as-is." + refund_clause
        )
    if kind == "critic_findings":
        return (
            "This version didn't pass the quality review. Regenerate, or override "
            "to finalise it as-is." + refund_clause
        )
    # Unknown / forward-compatible kind: stay honest about override availability.
    action = (
        "Regenerate, or override to finalise it as-is."
        if overridable
        else "Regenerate to continue."
    )
    return "This version is blocked by the quality gate. " + action + refund_clause


def derive_quality_gate_recovery(
    kind: str | None, *, refunded_prior_attempt: bool
) -> dict:
    """Derive the user-facing recovery contract for a blocked quality gate.

    A pure function of the gate ``kind`` and whether the blocking attempt was
    refunded. No DB state and no migration — the result is attached to the
    ``Stage.quality_gate`` property (so it ships in every stage GET and survives
    refresh) and to the structured finalise 409, so the frontend renders one
    authoritative recovery message from a single source of truth.
    """
    overridable = kind not in NON_OVERRIDABLE_GATE_KINDS
    return {
        "action": "regenerate",
        "overridable": overridable,
        "credit_required": GENERATION_CREDIT_COST,
        "refunded_prior_attempt": refunded_prior_attempt,
        "message": _recovery_message(
            kind, overridable=overridable, refunded=refunded_prior_attempt
        ),
    }


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
        # A blocked version carries a derived recovery contract so the frontend
        # has one authoritative source for "is this overridable / what does a
        # retry cost / was I refunded / what do I tell the user." An overridden
        # version is not awaiting recovery, so it carries none.
        if status == "blocked":
            payload["recovery"] = derive_quality_gate_recovery(
                self.quality_gate_kind,
                refunded_prior_attempt=bool(
                    payload.get("refunded_prior_attempt", False)
                ),
            )
        return payload

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID as PythonUUID

from sqlalchemy import Boolean, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.stage_version import StageVersion


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    stage_version_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stage_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage_type: Mapped[str] = mapped_column(Text, nullable=False)
    overall_score: Mapped[int | None] = mapped_column(Integer)
    completeness: Mapped[int | None] = mapped_column(Integer)
    clarity: Mapped[int | None] = mapped_column(Integer)
    coverage_percent: Mapped[int | None] = mapped_column(Integer)
    uncovered_reqs: Mapped[list[str] | None] = mapped_column(JSONB)
    tasks_without_ref: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    flagged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    structural_validator_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    # Which judge produced this score (issue #152). Scores from different judge
    # models are NOT comparable, and the judge moves with LLM_PROVIDER_PRIORITY
    # — so without this an ``overall_score`` trend line silently splices two
    # graders at whatever commit the provider flipped. Nullable with no backfill:
    # rows predating this column were all scored by the Anthropic judge, and
    # writing that in retroactively would assert a fact the row never recorded.
    judge_provider: Mapped[str | None] = mapped_column(Text)
    judge_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    stage_version: Mapped["StageVersion"] = relationship(back_populates="eval_results")

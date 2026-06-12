from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID as PythonUUID

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class LLMCostEvent(Base):
    """One row per LLM provider call — the Phase-0 cost ledger (issue #26).

    Append-only observability/audit table. Written fire-and-forget from the
    instrumentation layer so a ledger write can never break a generation. The
    foreign keys use ``ondelete="SET NULL"`` so cost history survives entity
    deletion (matching the billing-audit retention pattern), and every id is
    nullable because not every call belongs to every surface (e.g. a critic
    judge call has no stage_version, a storyboard call has no stage).
    """

    __tablename__ = "llm_cost_events"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Correlation to the Langfuse generation, reused for the deferred
    # quality_outcome update once the post-generation gates have run.
    generation_id: Mapped[str | None] = mapped_column(Text, index=True)

    # What ran.
    operation: Mapped[str | None] = mapped_column(Text, index=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_tier: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    stage_type: Mapped[str | None] = mapped_column(Text)

    # Token usage. reasoning_tokens is an observability breakout that is ALREADY
    # included in output_tokens and billed at the output rate — it is never
    # added to estimated_cost_usd.
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    usage_estimation_method: Mapped[str | None] = mapped_column(Text)

    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))

    latency_ms: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(Text)
    stopped_by_limit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    cache_hit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    batch: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    cross_provider_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    retry_count: Mapped[int | None] = mapped_column(Integer)
    repair_count: Mapped[int | None] = mapped_column(Integer)
    # Set by the deferred post-gate update: "passed" / "validator_failed" /
    # "critic_failed" / "error" / None (gates did not run / not applicable).
    quality_outcome: Mapped[str | None] = mapped_column(Text, index=True)

    credit_reason: Mapped[str | None] = mapped_column(Text)
    product_surface: Mapped[str | None] = mapped_column(Text, index=True)

    workspace_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        index=True,
    )
    stage_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stages.id", ondelete="SET NULL"),
        index=True,
    )
    storyboard_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("storyboards.id", ondelete="SET NULL"),
        index=True,
    )
    increment_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("increments.id", ondelete="SET NULL"),
        index=True,
    )

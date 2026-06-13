from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class LLMBatchJob(Base):
    """One durable checkpoint per deferred (batched) LLM call (Phase 3, issue #26).

    The provider Message Batches API is asynchronous (submit → poll → retrieve,
    up to 24h) and bills a batch whether or not its results are collected, so the
    submission *must* be durably checkpointed: the ``provider_batch_id`` is
    persisted the moment a batch is created, before submit is treated as done.
    The worker drives the lifecycle ``pending → submitted → completed | failed``;
    a successful collect deletes the row (the durable artifact is the persisted
    ``EvalResult``), a terminal failure leaves it ``failed`` for inspection +
    dead-letters to ``llm:batch:deadletter``.

    Only ``eval.score`` is wired today; ``operation`` is the discriminator so the
    table generalises to other non-interactive judge/eval work. The request and
    completion context are stored on the row so the job is self-contained and
    idempotent on re-run.
    """

    __tablename__ = "llm_batch_jobs"

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
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Lifecycle: pending → submitted → completed (row deleted) | failed.
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'"), index=True
    )
    # Submit/collect attempt counter for bounded retries before failing.
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    operation: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_tier: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)

    # The provider's batch id — NULL until submitted. Set (and committed) before
    # submit is treated as done so a paid-for batch is never lost. Indexed so the
    # poll cron can look the row up by the id the provider echoes back.
    provider_batch_id: Mapped[str | None] = mapped_column(Text, index=True)
    # The per-request custom_id inside the (batch-of-one) submission.
    custom_id: Mapped[str] = mapped_column(Text, nullable=False)

    # The submitted request payload.
    request_system: Mapped[str] = mapped_column(Text, nullable=False)
    request_user: Mapped[str] = mapped_column(Text, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    # Operation-specific data the completion handler needs to persist the result
    # (for eval.score: stage_version_id, stage_type, content, spec_content,
    # harness_content, content_generation_id).
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)

    error: Mapped[str | None] = mapped_column(Text)

    workspace_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        index=True,
    )

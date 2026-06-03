from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID as PythonUUID

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.integration_push import IntegrationPush


class IntegrationPushTask(Base):
    """Maps a task to its GitHub Issue and tracks completion for bidirectional
    sync (Phase 21, spec §10).

    Constraints/indexes mirror migration ``0016_github_living_integration.py``:
    the ``(push_id, task_ref)`` unique constraint is retained and an index is
    added on ``external_issue_number`` for webhook reconciliation lookups.
    """

    __tablename__ = "integration_push_tasks"
    __table_args__ = (
        UniqueConstraint(
            "push_id",
            "task_ref",
            name="uq_push_task_ref",
        ),
        Index(
            "ix_integration_push_tasks_issue_number",
            "external_issue_number",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    push_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integration_pushes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Content-stable across increments, e.g. T-001.
    task_ref: Mapped[str] = mapped_column(Text, nullable=False)
    external_issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # The increment that introduced/last changed this task. FK target
    # (increments.id) wired in migration 0017 (T-278); SET NULL on increment delete.
    increment_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("increments.id", ondelete="SET NULL"),
        nullable=True,
    )
    state: Mapped[Literal["open", "done"]] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'open'"),
    )
    # When the issue was observed closed.
    done_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
    )
    # How the task was completed: pr_merge (closed by a merged PR) | manual.
    done_via: Mapped[Literal["pr_merge", "manual"] | None] = mapped_column(
        Text,
    )
    # Last reconcile against GitHub.
    synced_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    push: Mapped["IntegrationPush"] = relationship(back_populates="tasks")

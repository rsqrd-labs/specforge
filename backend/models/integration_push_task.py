from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID as PythonUUID

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.integration_push import IntegrationPush


class IntegrationPushTask(Base):
    __tablename__ = "integration_push_tasks"
    __table_args__ = (
        UniqueConstraint(
            "push_id",
            "task_ref",
            name="uq_push_task_ref",
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
    task_ref: Mapped[str] = mapped_column(Text, nullable=False)
    external_issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    push: Mapped["IntegrationPush"] = relationship(back_populates="tasks")

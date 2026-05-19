from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID as PythonUUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.integration_push_task import IntegrationPushTask
    from models.user import User
    from models.workspace import Workspace


class IntegrationPush(Base):
    __tablename__ = "integration_pushes"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            name="uq_integration_push_workspace_provider",
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
        index=True,
    )
    user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    repo_full_name: Mapped[str | None] = mapped_column(Text)
    repo_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    pushed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    workspace: Mapped["Workspace"] = relationship()
    user: Mapped["User"] = relationship()
    tasks: Mapped[list["IntegrationPushTask"]] = relationship(
        back_populates="push",
        cascade="all, delete-orphan",
    )

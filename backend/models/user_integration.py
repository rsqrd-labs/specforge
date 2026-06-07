from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID as PythonUUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.user import User


class UserIntegration(Base):
    __tablename__ = "user_integrations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            name="uq_user_integration_provider",
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
        index=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_token = mapped_column(Text, nullable=False)
    github_username: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
    )

    user: Mapped["User"] = relationship()

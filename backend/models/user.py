from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID as PythonUUID

from sqlalchemy import CheckConstraint, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.credit_ledger import CreditLedger
    from models.workspace import Workspace


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "credit_balance >= 0",
            name="ck_users_credit_balance_nonnegative",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    google_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    credit_balance: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    workspaces: Mapped[list["Workspace"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    credit_ledger_entries: Mapped[list["CreditLedger"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

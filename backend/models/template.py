"""Starter Template ORM model — system-owned in V1.

Phase 14 / V1 spec §4.11 / Plan §18.3. The Template table powers the
dashboard Starter Templates strip and the workspace creation form
prefill. Templates are deploy-time-seeded via scripts/seed_templates.py
and rendered by the unauthenticated GET /templates endpoint.

Intentional design choice: this model has no foreign key to the users
table. Templates are owned by the Thought2Build platform itself, not by
any individual account. End-user-authored templates are explicitly
out of scope for V1 (see Spec §14) — they belong to V2.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID as PythonUUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_templates_slug"),
        CheckConstraint(
            "category IN ('auth', 'payments', 'content', 'realtime', 'agent', 'tooling')",  # noqa: E501
            name="ck_templates_category",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

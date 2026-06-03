from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID as PythonUUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.workspace import Workspace


class Increment(Base):
    """A versioned delta layered on a finalised workspace baseline (spec §10,
    §4.14.7).

    Increment 0 is the original baseline; each subsequent ``sequence`` (1, 2, 3…
    per workspace) captures an additive or behaviour-changing change set.
    ``baseline_version_ids`` pins the immutable ``StageVersion.id`` values that
    delta generation (T-279) treats as fixed context, so an increment is
    reproducible even as the workspace continues to evolve.

    Mirrors migration ``0017_increments.py`` one-for-one (the
    ``(workspace_id, sequence)`` uniqueness) to keep the ORM and schema in sync.
    """

    __tablename__ = "increments"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "sequence",
            name="uq_increment_workspace_sequence",
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
    # 1, 2, 3… per workspace; unique with workspace_id.
    sequence: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[Literal["draft", "generating", "ready", "pushed", "stale"]] = (
        mapped_column(
            Text,
            nullable=False,
            server_default=text("'draft'"),
        )
    )
    # Immutable StageVersion.id values forming the baseline context for the delta.
    baseline_version_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
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

    workspace: Mapped["Workspace"] = relationship()


class IncrementIdea(Base):
    """A lightweight backlog item — a feature captured mid-build, batched into an
    increment when ready (spec §10).

    May originate in SpecForge (``source='user'``) or flow back from a GitHub
    issue labelled ``idea``/``enhancement`` (``source='github'``,
    ``external_ref='gh-issue:123'``) via the §4.14.3 webhook (T-280).
    ``increment_id`` is set when the idea is pulled into an increment.
    """

    __tablename__ = "increment_ideas"

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
    # Set when the idea is pulled into an increment; SET NULL keeps the idea in
    # the backlog if its increment is later removed.
    increment_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("increments.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[Literal["user", "github"]] = mapped_column(Text, nullable=False)
    # e.g. gh-issue:123 when sourced from GitHub.
    external_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[Literal["open", "planned", "done", "dismissed"]] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'open'"),
    )
    # The captured feature idea. Declared after status so the ``text`` column name
    # never shadows the imported ``text()`` used in earlier server_defaults.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    workspace: Mapped["Workspace"] = relationship()
    increment: Mapped["Increment | None"] = relationship()

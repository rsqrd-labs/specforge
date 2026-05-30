from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID as PythonUUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.credit_ledger import CreditLedger
    from models.user import User
    from models.workspace import Workspace


class Storyboard(Base):
    """A generated Storyboard launch keynote (Phase 20, T-250).

    A Storyboard is *not* a fifth pipeline stage. It is an immutable, versioned
    artifact derived from the finalised SPEC / PLAN / HARNESS / TASKS
    ``StageVersion`` rows of a workspace. Each generated version is one row.
    ``source_stage_version_ids`` pins the exact source versions so a later edit
    to the workspace cannot silently mutate an already-generated Storyboard;
    when sources move on the Storyboard is marked ``stale`` rather than rewritten.
    """

    __tablename__ = "storyboards"
    __table_args__ = (
        # One row per generated version of a workspace's Storyboard.
        UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_storyboards_workspace_version",
        ),
        # A public share slug, when present, must be globally unique. The slug is
        # NULL until the owner enables sharing, so the uniqueness is enforced via
        # a partial index (see migration) rather than a plain UNIQUE constraint.
        Index(
            "uq_storyboards_public_share_slug",
            "public_share_slug",
            unique=True,
            postgresql_where=text("public_share_slug IS NOT NULL"),
        ),
        Index(
            "ix_storyboards_workspace_created_at",
            "workspace_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_storyboards_user_created_at",
            "user_id",
            text("created_at DESC"),
        ),
        CheckConstraint("version > 0", name="ck_storyboards_version"),
        CheckConstraint(
            "status IN ('generating', 'ready', 'failed', 'stale')",
            name="ck_storyboards_status",
        ),
        CheckConstraint(
            "char_length(title) <= 200",
            name="ck_storyboards_title_len",
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
    )
    user_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    theme: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    speaker_notes_md: Mapped[str] = mapped_column(Text, nullable=False)
    demo_script_md: Mapped[str] = mapped_column(Text, nullable=False)
    technical_appendix_md: Mapped[str] = mapped_column(Text, nullable=False)
    source_map_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_stage_version_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    # NO ACTION (the default — no ondelete) on purpose. The Storyboard Delivery
    # Directive forbids deleting a referenced credit_ledger entry, so we must NOT
    # use SET NULL (as stage.deduction_ledger_id does) or RESTRICT here. NO ACTION
    # defers the referential check to end-of-statement, so a user cascade delete —
    # which removes both this storyboard (via user_id) and the ledger row (via
    # credit_ledger.user_id) in the same statement — still succeeds, while a stray
    # attempt to delete only the ledger row is rejected.
    credit_ledger_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credit_ledger.id"),
        nullable=True,
    )
    public_share_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_share_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    allow_pdf_download: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    allow_notes_download: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    allow_appendix_download: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    allow_source_layer: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
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

    # One-directional relationships: convenient for the service layer without
    # forcing collections (and their cascade semantics) onto User/Workspace.
    workspace: Mapped["Workspace"] = relationship()
    user: Mapped["User"] = relationship()
    credit_ledger: Mapped["CreditLedger | None"] = relationship()

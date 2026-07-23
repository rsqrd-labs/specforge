"""SQLAlchemy ORM model for github_installations.

One row per GitHub App installation — the v2 identity that replaces the per-user
OAuth token (the legacy ``UserIntegration`` path, retained for migration). It
records which account/org granted the App and which repositories it may act on.

The App private key and minted installation tokens are **not** stored here: the
key lives in a secret manager / config and tokens are cached short-TTL in Redis
(spec §8). This table only persists durable installation identity.

Phase 21 — T-265 / T-266 (spec §10).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID as PythonUUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models import Base

if TYPE_CHECKING:
    from models.user import User


class GitHubInstallation(Base):
    __tablename__ = "github_installations"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            name="uq_github_installation_installation_id",
        ),
        CheckConstraint(
            "pr_check_mode IN ('off', 'manual', 'auto')",
            name="ck_github_installation_pr_check_mode",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # GitHub's numeric installation id (distinct from the App id). UNIQUE.
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_login: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[Literal["User", "Organization"]] = mapped_column(
        Text,
        nullable=False,
    )
    repository_selection: Mapped[Literal["all", "selected"]] = mapped_column(
        Text,
        nullable=False,
    )
    # Issue #27 Phase 4 — per-installation control over the PR-diff judge:
    #   off    → never judge; post a neutral "disabled by setting" check.
    #   manual → judge only on an explicit GitHub re-run (check_suite
    #            rerequested); an automatic push posts a neutral "re-run to
    #            evaluate" check and spends no judge call.
    #   auto   → judge on every routed push (the pre-Phase-4 behaviour).
    # Defaults to "manual" so the judge is opt-in (the issue #27 cost cut).
    pr_check_mode: Mapped[Literal["off", "manual", "auto"]] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'manual'"),
    )
    # The Thought2Build user who installed, if known. SET NULL on user delete: the
    # installation outlives the linking account.
    user_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Set when GitHub reports the install suspended.
    suspended_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
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

    user: Mapped["User | None"] = relationship()

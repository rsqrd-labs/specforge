"""Pydantic schemas for the increment timeline + idea backlog (Phase 21 — T-280).

These back the increment REST surface (``GET/POST /workspaces/{id}/increments``,
``POST .../increments/{inc_id}/push``) and the idea backlog
(``GET/POST /workspaces/{id}/ideas``) consumed by the frontend timeline (T-289).

Conventions mirror ``schemas/github.py``: request models set ``extra="forbid"``
so an unexpected field is a 422, and read models are ``from_attributes`` views of
the ORM rows the owner-scoped router populates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# The increment lifecycle (spec §10, mirrors models/increment.py).
IncrementStatus = Literal["draft", "generating", "ready", "pushed", "stale"]

# Where a backlog idea originated and its lifecycle (spec §10).
IdeaSource = Literal["user", "github"]
IdeaStatus = Literal["open", "planned", "done", "dismissed"]

# Delta generation mode. The MVP ships ``additive`` only; ``behaviour_changing``
# (blast-radius analysis) stays gated behind a flag in the service (T-279).
IncrementMode = Literal["additive", "behaviour_changing"]


class IncrementCreate(BaseModel):
    """Request body for generating an increment from a feature request (T-279)."""

    feature_request: str = Field(min_length=8, max_length=4000)
    mode: IncrementMode = "additive"

    model_config = ConfigDict(extra="forbid")


class IncrementRead(BaseModel):
    """One entry on the workspace's increment timeline."""

    id: UUID
    sequence: int
    title: str
    status: IncrementStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncrementGenerateResponse(IncrementRead):
    """Result of ``POST /increments`` — the new increment plus its delta size."""

    new_task_count: int = 0


class IncrementPushResponse(BaseModel):
    """The 202 ack for ``POST /increments/{inc_id}/push``."""

    increment_id: UUID
    status: IncrementStatus


class IdeaCreate(BaseModel):
    """Request body for capturing a user idea into the backlog."""

    text: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class IdeaRead(BaseModel):
    """One backlog idea (user-captured or flowed back from a GitHub label)."""

    id: UUID
    source: IdeaSource
    external_ref: str | None = None
    status: IdeaStatus
    text: str
    increment_id: UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PushStatus = Literal["pending", "in_progress", "success", "error"]
Visibility = Literal["public", "private"]


class GitHubStatusResponse(BaseModel):
    """Response shape for GET /integrations/github."""

    connected: bool
    github_username: str | None

    model_config = ConfigDict(from_attributes=True)


class GitHubExportRequest(BaseModel):
    """Request body for POST /workspaces/{id}/export/github.

    The repo_name pattern is intentionally strict — GitHub accepts more
    characters, but limiting to [a-zA-Z0-9._-] blocks path-traversal-style
    inputs and makes the resulting repo URL safe to surface verbatim.
    """

    repo_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9._-]+$",
    )
    visibility: Visibility


class GitHubExportResponse(BaseModel):
    """Response from POST /workspaces/{id}/export/github."""

    push_id: UUID
    status: PushStatus
    repo_full_name: str | None
    repo_url: str | None
    issue_count: int

    model_config = ConfigDict(from_attributes=True)


class IntegrationPushRead(BaseModel):
    """Response from GET /workspaces/{id}/export/github."""

    push_id: UUID = Field(alias="id")
    status: PushStatus
    repo_full_name: str | None
    repo_url: str | None
    issue_count: int
    pushed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

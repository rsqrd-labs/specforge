"""Pydantic schemas for the Phase 21 GitHub living-integration API surface
(T-266).

This is the v2 (GitHub App) contract. The Phase 13 one-shot OAuth export schemas
in ``schemas/integration.py`` are retained unedited (append-only) and still serve
the legacy path; these models serve the App install flow (T-270), the worker
export (T-269/T-276), and bidirectional sync (T-272/T-273).

Security invariants (spec §8, §10):
  - No schema echoes installation tokens, the App private key, webhook secrets,
    or raw webhook payloads — only durable, non-secret identity/state.
  - ``SyncStateResponse`` / ``InstallationList`` are owner-scoped responses; the
    router enforces ownership before populating them.
  - Request models set ``extra="forbid"`` so an unexpected field is a 422, not a
    silent passthrough.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# v2 export modes (spec §4.14): plain file push to the default branch, or a
# branch + PR carrying a red harness scaffold (T-276).
ExportMode = Literal["files_to_default", "pr_with_tests"]

# The v2 push lifecycle (spec §10). There is deliberately no ``active`` literal:
# a "live" push is any non-``failed`` row (see services/integrations/push_repo).
PushStatus = Literal["pending", "completed", "failed", "stale"]

# Per-task bidirectional sync state (spec §10).
TaskState = Literal["open", "done"]
TaskVersionSyncStatus = Literal["up_to_date", "changes_pending", "unknown"]
DoneVia = Literal["pr_merge", "manual"]
InboundSyncError = Literal["installation_unavailable"]

# GitHub App installation account shape (spec §10).
AccountType = Literal["User", "Organization"]
RepositorySelection = Literal["all", "selected"]

# Repo visibility for a freshly created export repository.
Visibility = Literal["public", "private"]


class InstallationStatus(BaseModel):
    """Owner-facing summary of a user's GitHub integration status.

    The v2 analogue of the legacy ``GitHubStatusResponse``. ``on_legacy_oauth``
    is the migration signal: the user still holds a v1 OAuth token and the UI
    should offer the App-install migration (T-270). It is surfaced here, at the
    user-level status, so it is present even when the user has zero App
    installations yet.
    """

    connected: bool
    account_login: str | None = None
    account_type: AccountType | None = None
    repository_selection: RepositorySelection | None = None
    username: str | None = None
    on_legacy_oauth: bool = False

    model_config = ConfigDict(from_attributes=True)


class InstallationOption(BaseModel):
    """One installation a user may target when exporting.

    ``id`` is the SpecForge ``github_installations`` row id and is what
    :class:`GitHubExportRequest` references; ``installation_id`` is GitHub's
    numeric id, exposed for display/debugging only.
    """

    id: UUID
    installation_id: int
    account_login: str
    account_type: AccountType
    repository_selection: RepositorySelection
    suspended: bool = False

    model_config = ConfigDict(from_attributes=True)


class InstallationList(BaseModel):
    """The set of installations a user can export under (org + personal).

    A user may install the App on several accounts; the export picker chooses a
    target from this list (T-269/T-270).
    """

    installations: list[InstallationOption]
    on_legacy_oauth: bool = False

    model_config = ConfigDict(from_attributes=True)


class RepoOption(BaseModel):
    """One repository an installation can export into (the repo-picker feed).

    ``id`` is GitHub's immutable numeric repo id (the same value persisted as
    ``IntegrationPush.repo_id``); ``name`` is the bare name the picker submits
    as :class:`GitHubExportRequest.repo_name`.
    """

    id: int
    name: str
    full_name: str
    private: bool = False
    html_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RepoList(BaseModel):
    """Repositories reachable by one installation, plus the create-repo gate.

    ``can_create`` is computed server-side from the same helper the worker
    export uses (``installation_can_create_repos``), so the UI's "create a new
    repo" affordance cannot drift from what the export will actually do.
    ``truncated`` flags that GitHub holds more repositories than the capped
    listing returned — the picker keeps a type-a-name escape hatch for those.
    """

    repositories: list[RepoOption]
    truncated: bool = False
    can_create: bool = False

    model_config = ConfigDict(from_attributes=True)


class GitHubExportRequest(BaseModel):
    """Request body for the v2 worker export (POST returns 202; spec §11).

    The request must name **which installation** to create/use the repo under,
    because a multi-install user's token is resolved per installation
    (T-267/T-269). ``installation_id`` is the ``github_installations`` row id
    (not GitHub's numeric id). The ``repo_name`` pattern is intentionally strict
    — GitHub accepts more characters, but limiting to ``[a-zA-Z0-9._-]`` blocks
    path-traversal-style inputs and keeps the resulting repo URL safe to surface
    verbatim.
    """

    installation_id: UUID
    repo_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9._-]+$",
    )
    export_mode: ExportMode = "files_to_default"
    visibility: Visibility = "private"

    model_config = ConfigDict(extra="forbid")


class PushStatusResponse(BaseModel):
    """Status of a workspace's live push (poll target for the 202 export)."""

    push_id: UUID = Field(alias="id")
    status: PushStatus
    export_mode: ExportMode
    branch_name: str | None = None
    pr_number: int | None = None
    shipped: int = 0
    total: int = 0
    repo_full_name: str | None = None
    repo_url: str | None = None
    pushed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TaskSyncState(BaseModel):
    """One task's bidirectional sync state (spec §10)."""

    task_ref: str
    # ``validation_alias`` (not ``alias``) so this populates from the ORM column
    # ``external_issue_number`` while still *serialising* under the field name
    # ``issue_number`` — FastAPI's response serialisation defaults to
    # ``by_alias=True``, and a plain ``alias`` would leak the DB column name into
    # the JSON, which the frontend contract (``issue_number``) never reads.
    issue_number: int = Field(validation_alias="external_issue_number")
    state: TaskState
    done_via: DoneVia | None = None
    done_at: datetime | None = None
    synced_at: datetime | None = None
    # Human-facing identity resolved from the push's *source* Tasks version
    # (drift-proof: it matches the very ``task_ref``s that produced these issues).
    # ``human_ref`` is the ``T-NNN`` number and ``title`` the task heading; both
    # are ``None`` when the source version is gone or the row is an increment task
    # not present in the baseline, in which case the UI falls back to the issue
    # number. The opaque ``task_ref`` hash is never shown to users.
    human_ref: str | None = None
    title: str | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SyncStateResponse(BaseModel):
    """Owner-scoped bidirectional sync view for a workspace's live push.

    ``out_of_sync`` is the drift signal (T-273): the push's source Tasks version
    no longer matches the workspace's current finalised Tasks, so the issues on
    GitHub may be stale relative to the spec.
    """

    push_id: UUID
    status: PushStatus
    task_sync_status: TaskVersionSyncStatus = "unknown"
    sync_paused: bool = False
    out_of_sync: bool = False
    shipped: int = 0
    total: int = 0
    last_inbound_sync_at: datetime | None = None
    last_inbound_sync_error: InboundSyncError | None = None
    tasks: list[TaskSyncState]

    model_config = ConfigDict(from_attributes=True)


class SyncRefreshAccepted(BaseModel):
    """Acknowledgement for an inbound refresh queued on the fast worker.

    ``requested_at`` is compared with ``SyncStateResponse.last_inbound_sync_at``
    so clients can distinguish queue admission from completed reconciliation.
    """

    push_id: UUID
    requested_at: datetime


class ExportSummary(BaseModel):
    """One row of the account-wide exports hub (``GET
    /integrations/github/exports``): a workspace's live GitHub export summarised
    for a list view — repo coordinates, lifecycle status, drift, and issue
    completion — without the full per-task payload the detail ``/sync`` carries.
    """

    workspace_id: UUID
    workspace_name: str
    push_id: UUID
    status: PushStatus
    export_mode: ExportMode
    repo_full_name: str | None = None
    repo_url: str | None = None
    pr_number: int | None = None
    task_sync_status: TaskVersionSyncStatus = "unknown"
    sync_paused: bool = False
    out_of_sync: bool = False
    shipped: int = 0
    total: int = 0
    pushed_at: datetime | None = None
    last_inbound_sync_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class WebhookAck(BaseModel):
    """The fast 2xx body returned to GitHub after a webhook is received.

    ``accepted`` — verified and a reconcile job was enqueued; ``skipped`` — a
    duplicate ``X-GitHub-Delivery`` already recorded (idempotent no-op);
    ``ignored`` — an event type this integration does not act on. The body never
    carries payload contents.
    """

    status: Literal["accepted", "skipped", "ignored"] = "accepted"

    model_config = ConfigDict(extra="forbid")

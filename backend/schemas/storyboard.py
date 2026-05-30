"""Pydantic schemas for the Storyboard API surface (Phase 20 — T-251).

These models define the owner and public API contracts for Storyboard launch
keynotes. The strict structured-output payload models the LLM must produce
(``StoryboardPayload`` and friends) live in ``prompts/storyboard.py`` (T-253);
here the generated ``content`` / ``presentation`` payload is carried as an
already-validated JSON object so read endpoints never re-run generation-time
validation.

Privacy invariant: every public-facing model sets ``extra="forbid"`` so adding
any field to an unauthenticated surface is a deliberate, reviewable change and
never a silent ORM passthrough. The public response is allow-list based and must
never expose account email, user id, workspace id, credit data, billing data,
source stage version ids, raw prompts, or previous versions — see
``harness/schemas/storyboard-public-response.schema.json``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Lifecycle states for a generated Storyboard version. ``generating`` is the
# in-flight placeholder, ``ready`` is presentable, ``failed`` is a refunded dead
# version, and ``stale`` marks a once-ready version whose source stages were
# refinalised.
StoryboardStatus = Literal["generating", "ready", "failed", "stale"]

# Owner download artifacts. ``html`` and ``pdf`` are rendered packages (T-255);
# ``notes`` / ``demo-script`` / ``appendix`` are markdown documents.
StoryboardDownloadKind = Literal["html", "pdf", "notes", "demo-script", "appendix"]

# Notes can be downloaded as raw markdown or a rendered PDF.
StoryboardNotesFormat = Literal["md", "pdf"]

# Public downloads are a strict subset of owner downloads: the offline HTML
# package is never offered publicly, and every kind here is gated behind the
# matching ``allow_*`` permission.
StoryboardPublicDownloadKind = Literal["pdf", "notes", "demo-script", "appendix"]


class StoryboardSharePermissions(BaseModel):
    """The four independent public-share permission toggles.

    Defaults mirror the column defaults: PDF download on, everything else off.
    """

    allow_pdf_download: bool = True
    allow_notes_download: bool = False
    allow_appendix_download: bool = False
    allow_source_layer: bool = False

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Owner responses
# ---------------------------------------------------------------------------


class StoryboardSummary(BaseModel):
    """Lightweight owner list item — no heavy payload, notes, or source map."""

    id: UUID
    workspace_id: UUID
    version: int
    status: StoryboardStatus
    title: str
    theme: str
    public_share_enabled: bool
    public_share_slug: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class StoryboardDetail(BaseModel):
    """Full owner view of a single Storyboard version.

    Carries the validated presentation payload and source map. The markdown
    artifacts (speaker notes, demo script, appendix) are fetched via the
    download endpoints rather than inlined here to keep the response bounded.
    """

    id: UUID
    workspace_id: UUID
    version: int
    status: StoryboardStatus
    title: str
    theme: str
    content: dict[str, Any]
    source_map: dict[str, Any]
    public_share_enabled: bool
    public_share_slug: str | None = None
    permissions: StoryboardSharePermissions
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class StoryboardPresenterResponse(BaseModel):
    """Owner presenter-mode view: slides plus per-slide speaker notes.

    ``notes`` is the speaker-note map keyed by slide id, lifted from the
    validated payload so presenter mode does not depend on the rendered
    markdown artifact.
    """

    id: UUID
    title: str
    status: StoryboardStatus
    theme: str
    content: dict[str, Any]
    notes: dict[str, Any]
    demo_script_md: str

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class StoryboardGenerateRequest(BaseModel):
    """Body for full generation / regeneration (25 credits).

    No fields today — workspace and user are taken from the path and the
    authenticated session — but kept as an explicit model so future generation
    options (e.g. theme hints) are an additive, reviewable change. ``extra`` is
    forbidden so unknown client fields are rejected rather than silently dropped.
    """

    model_config = ConfigDict(extra="forbid")


class StoryboardRegenerateSectionRequest(BaseModel):
    """Body for single-section regeneration (5 credits).

    The section id is a path parameter; the body is reserved for future options
    and currently carries no fields.
    """

    model_config = ConfigDict(extra="forbid")


class StoryboardShareRequest(BaseModel):
    """Enable public sharing and/or update permissions.

    Each permission is optional: ``None`` leaves the current value unchanged (or
    falls back to the default on first enable). The slug is server-generated and
    never client-supplied.
    """

    allow_pdf_download: bool | None = None
    allow_notes_download: bool | None = None
    allow_appendix_download: bool | None = None
    allow_source_layer: bool | None = None

    model_config = ConfigDict(extra="forbid")


class StoryboardShareResponse(BaseModel):
    """Owner-facing result of enabling/rotating a public share."""

    slug: str
    url: str
    enabled: bool
    permissions: StoryboardSharePermissions

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Public response (allow-list, unauthenticated)
# ---------------------------------------------------------------------------


class StoryboardPublicResponse(BaseModel):
    """Allow-list contract for GET /storyboards/public/{slug}.

    Schema-locked to ``harness/schemas/storyboard-public-response.schema.json``.
    ``extra="forbid"`` is the privacy guard: this surface must never carry
    ``user_id``, ``workspace_id``, ``credit_ledger_id``, ``source_stage_version_ids``,
    account email, credit balance, billing history, draft/previous versions, or
    private notes/appendix/source excerpts unless the matching permission is on.
    """

    title: str = Field(min_length=1, max_length=200)
    presentation: dict[str, Any]
    permissions: StoryboardSharePermissions
    downloads: list[StoryboardPublicDownloadKind] = Field(default_factory=list)
    shared_at: datetime

    model_config = ConfigDict(extra="forbid")

"""Storyboard owner and public API router (Phase 20 — T-251).

This module owns the Storyboard HTTP contract: route registration, auth and
ownership boundaries, CSRF posture, response shapes, public privacy headers, and
download streaming semantics. Generation, rendering, and public allow-list
filtering are deliberately delegated to services delivered by later tasks:

* generation / regeneration / section regeneration  -> T-254 storyboard_service
* HTML and PDF rendered downloads                    -> T-255 storyboard_renderer
* public allow-list response building + slug/share   -> T-256 storyboard_public_service

Endpoints whose body is owned by a later task return a typed 503
``storyboard_pipeline_unavailable`` until that task wires its service in. The
owner read endpoints and the markdown download endpoints depend only on the
T-250 model and are fully implemented here.

Security notes:
* Owner routes depend on ``get_current_user`` and scope every lookup to the
  caller's ``user_id``; a missing or non-owned id returns 404 (never 4xx that
  would confirm existence to another account).
* Mutating routes are ordinary POST/DELETE routes, so ``CsrfMiddleware``
  enforces CSRF on them — they are intentionally never added to the CSRF
  exemption list.
* Public routes are unauthenticated and read-only, always emit ``noindex`` and a
  strict framing-proof CSP, and never cache (share permissions can change).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.auth import get_current_user
from models import Storyboard, User
from schemas.storyboard import (
    StoryboardDetail,
    StoryboardGenerateRequest,
    StoryboardNotesFormat,
    StoryboardPresenterResponse,
    StoryboardRegenerateSectionRequest,
    StoryboardSharePermissions,
    StoryboardShareRequest,
    StoryboardShareResponse,
    StoryboardSummary,
)
from services.workspace_service import workspace_service

logger = logging.getLogger(__name__)

# Single router, no prefix: each route carries its full path so the two distinct
# owner prefixes (/workspaces/{id}/storyboards and /storyboards/{id}) and the
# public surface live together with explicit, greppable paths.
router = APIRouter(tags=["storyboards"])

# Versions that can be presented or downloaded. A failed/generating version has
# no presentable artifact; ``stale`` stays presentable per the directive that a
# failed regeneration must leave the prior ready Storyboard intact.
_PRESENTABLE: frozenset[str] = frozenset({"ready", "stale"})

# Strict CSP for the unauthenticated public Storyboard surface. Mirrors the
# workspace public-share CSP: no scripts, framing forbidden, no remote assets.
_PUBLIC_STORYBOARD_CSP = (
    "default-src 'none'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "script-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


def _public_headers() -> dict[str, str]:
    """Headers applied to every public Storyboard response, including 404s.

    ``no-store`` because a viewer's allowed downloads can change the moment the
    owner toggles a permission or rotates the slug — nothing here is safe to
    cache at a shared layer.
    """

    return {
        "X-Robots-Tag": "noindex, nofollow",
        "Content-Security-Policy": _PUBLIC_STORYBOARD_CSP,
        "Cache-Control": "no-store, private",
    }


def _pipeline_unavailable(component: str) -> HTTPException:
    """Typed 503 for endpoints whose service lands in a later Phase 20 task.

    The component names which downstream service is not yet wired so the
    intermediate state is explicit to clients and logs.
    """

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "storyboard_pipeline_unavailable", "component": component},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="not_found",
    )


def _permissions(sb: Storyboard) -> StoryboardSharePermissions:
    return StoryboardSharePermissions(
        allow_pdf_download=sb.allow_pdf_download,
        allow_notes_download=sb.allow_notes_download,
        allow_appendix_download=sb.allow_appendix_download,
        allow_source_layer=sb.allow_source_layer,
    )


def _summary(sb: Storyboard) -> StoryboardSummary:
    return StoryboardSummary(
        id=sb.id,
        workspace_id=sb.workspace_id,
        version=sb.version,
        status=sb.status,
        title=sb.title,
        theme=sb.theme,
        public_share_enabled=sb.public_share_enabled,
        public_share_slug=sb.public_share_slug,
        created_at=sb.created_at,
        updated_at=sb.updated_at,
    )


def _detail(sb: Storyboard) -> StoryboardDetail:
    return StoryboardDetail(
        id=sb.id,
        workspace_id=sb.workspace_id,
        version=sb.version,
        status=sb.status,
        title=sb.title,
        theme=sb.theme,
        content=sb.content_json,
        source_map=sb.source_map_json,
        public_share_enabled=sb.public_share_enabled,
        public_share_slug=sb.public_share_slug,
        permissions=_permissions(sb),
        created_at=sb.created_at,
        updated_at=sb.updated_at,
    )


def _presenter(sb: Storyboard) -> StoryboardPresenterResponse:
    content: dict[str, Any] = sb.content_json or {}
    notes = content.get("notes") if isinstance(content, dict) else None
    return StoryboardPresenterResponse(
        id=sb.id,
        title=sb.title,
        status=sb.status,
        theme=sb.theme,
        content=content,
        notes=notes if isinstance(notes, dict) else {},
        demo_script_md=sb.demo_script_md,
    )


async def _get_owned_storyboard(
    storyboard_id: UUID, user: User, db: AsyncSession
) -> Storyboard:
    """Load a Storyboard scoped to its owner, or raise 404.

    Filtering on ``user_id`` is the IDOR guard: a Storyboard owned by another
    account is indistinguishable from a non-existent one. We never return 4xx
    that would confirm the row exists.
    """

    result = await db.execute(
        select(Storyboard).where(
            Storyboard.id == storyboard_id,
            Storyboard.user_id == user.id,
        )
    )
    sb = result.scalar_one_or_none()
    if sb is None:
        raise _not_found()
    return sb


def _markdown_download(body: str, filename: str, status_value: str) -> Response:
    """Stream a stored markdown artifact as an attachment.

    Served as a download (never rendered inline) with ``nosniff`` so the browser
    cannot be coaxed into interpreting the markdown as HTML.
    """

    if status_value not in _PRESENTABLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "storyboard_not_ready"},
        )
    return Response(
        content=body.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Owner — workspace-scoped collection
# ---------------------------------------------------------------------------


@router.get(
    "/workspaces/{id}/storyboards",
    response_model=list[StoryboardSummary],
)
async def list_workspace_storyboards(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StoryboardSummary]:
    # Ownership of the workspace is the gate; get() raises 404 if not the user's.
    await workspace_service.get(id, user.id, db)
    result = await db.execute(
        select(Storyboard)
        .where(Storyboard.workspace_id == id, Storyboard.user_id == user.id)
        .order_by(Storyboard.version.desc())
    )
    return [_summary(sb) for sb in result.scalars().all()]


@router.get(
    "/workspaces/{id}/storyboards/latest",
    response_model=StoryboardDetail,
)
async def get_latest_workspace_storyboard(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardDetail:
    """Return the highest-version Storyboard for the workspace, or 404 if none.

    Selection is the newest version row; the response carries ``status`` so the
    client can decide how to present an in-flight or failed latest version while
    a previously ready version remains available via the list endpoint.
    """

    await workspace_service.get(id, user.id, db)
    result = await db.execute(
        select(Storyboard)
        .where(Storyboard.workspace_id == id, Storyboard.user_id == user.id)
        .order_by(Storyboard.version.desc())
        .limit(1)
    )
    sb = result.scalar_one_or_none()
    if sb is None:
        raise _not_found()
    return _detail(sb)


@router.post(
    "/workspaces/{id}/storyboards",
    response_model=StoryboardDetail,
    status_code=status.HTTP_201_CREATED,
)
async def generate_storyboard(
    id: UUID,
    payload: StoryboardGenerateRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardDetail:
    """Generate a new Storyboard from the workspace's finalised stages (25 credits).

    Ownership is validated up front so an unauthorised caller gets 404 before any
    pipeline work. The generation flow itself is wired in T-254.
    """

    await workspace_service.get(id, user.id, db)
    raise _pipeline_unavailable("generation")


# ---------------------------------------------------------------------------
# Owner — single Storyboard
# ---------------------------------------------------------------------------


@router.get("/storyboards/{id}", response_model=StoryboardDetail)
async def get_storyboard(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardDetail:
    sb = await _get_owned_storyboard(id, user, db)
    return _detail(sb)


@router.post("/storyboards/{id}/regenerate", response_model=StoryboardDetail)
async def regenerate_storyboard(
    id: UUID,
    payload: StoryboardGenerateRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardDetail:
    """Full regeneration into a new version (25 credits). Wired in T-254."""

    await _get_owned_storyboard(id, user, db)
    raise _pipeline_unavailable("generation")


@router.post(
    "/storyboards/{id}/sections/{section_id}/regenerate",
    response_model=StoryboardDetail,
)
async def regenerate_storyboard_section(
    id: UUID,
    section_id: str,
    payload: StoryboardRegenerateSectionRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardDetail:
    """Regenerate a single section into a new version (5 credits). Wired in T-254."""

    await _get_owned_storyboard(id, user, db)
    raise _pipeline_unavailable("generation")


@router.get("/storyboards/{id}/presenter", response_model=StoryboardPresenterResponse)
async def get_storyboard_presenter(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardPresenterResponse:
    sb = await _get_owned_storyboard(id, user, db)
    if sb.status not in _PRESENTABLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "storyboard_not_ready"},
        )
    return _presenter(sb)


# ---------------------------------------------------------------------------
# Owner — downloads
# ---------------------------------------------------------------------------


@router.get("/storyboards/{id}/download/html")
async def download_storyboard_html(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Offline HTML keynote package. Rendered by the trusted renderer in T-255."""

    await _get_owned_storyboard(id, user, db)
    raise _pipeline_unavailable("renderer")


@router.get("/storyboards/{id}/download/pdf")
async def download_storyboard_pdf(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Static PDF keynote. Rendered via the no-network PDF executor in T-255."""

    await _get_owned_storyboard(id, user, db)
    raise _pipeline_unavailable("renderer")


@router.get("/storyboards/{id}/download/notes")
async def download_storyboard_notes(
    id: UUID,
    format: StoryboardNotesFormat = Query(default="md"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Speaker notes as markdown (now) or rendered PDF (T-255)."""

    sb = await _get_owned_storyboard(id, user, db)
    if format == "pdf":
        # PDF rendering of notes belongs to the trusted renderer (T-255).
        raise _pipeline_unavailable("renderer")
    return _markdown_download(
        sb.speaker_notes_md,
        f"specforge-storyboard-{sb.id}-speaker-notes.md",
        sb.status,
    )


@router.get("/storyboards/{id}/download/demo-script")
async def download_storyboard_demo_script(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    sb = await _get_owned_storyboard(id, user, db)
    return _markdown_download(
        sb.demo_script_md,
        f"specforge-storyboard-{sb.id}-demo-script.md",
        sb.status,
    )


@router.get("/storyboards/{id}/download/appendix")
async def download_storyboard_appendix(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    sb = await _get_owned_storyboard(id, user, db)
    return _markdown_download(
        sb.technical_appendix_md,
        f"specforge-storyboard-{sb.id}-technical-appendix.md",
        sb.status,
    )


# ---------------------------------------------------------------------------
# Owner — public share management
# ---------------------------------------------------------------------------


@router.post("/storyboards/{id}/share", response_model=StoryboardShareResponse)
async def enable_storyboard_share(
    id: UUID,
    payload: StoryboardShareRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardShareResponse:
    """Enable public sharing / update permissions. Slug + filtering land in T-256."""

    await _get_owned_storyboard(id, user, db)
    raise _pipeline_unavailable("public_sharing")


@router.delete("/storyboards/{id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def disable_storyboard_share(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Disable public sharing (slug preserved for re-enable). Wired in T-256."""

    await _get_owned_storyboard(id, user, db)
    raise _pipeline_unavailable("public_sharing")


@router.post("/storyboards/{id}/share/rotate", response_model=StoryboardShareResponse)
async def rotate_storyboard_share(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardShareResponse:
    """Rotate the public slug, invalidating the old link immediately. Wired in T-256."""

    await _get_owned_storyboard(id, user, db)
    raise _pipeline_unavailable("public_sharing")


# ---------------------------------------------------------------------------
# Public — unauthenticated, read-only
# ---------------------------------------------------------------------------


async def _lookup_public_storyboard(slug: str, db: AsyncSession) -> Storyboard | None:
    """Resolve a shareable Storyboard by slug.

    Returns ``None`` (→ 404) for unknown, disabled, or non-presentable slugs so
    the existence of any private Storyboard is never leaked.
    """

    result = await db.execute(
        select(Storyboard).where(
            Storyboard.public_share_slug == slug,
            Storyboard.public_share_enabled.is_(True),
        )
    )
    sb = result.scalar_one_or_none()
    if sb is None or sb.status not in _PRESENTABLE:
        return None
    return sb


@router.get("/storyboards/public/{slug}")
async def get_public_storyboard(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Public allow-list view of a shared Storyboard.

    The lookup, 404 semantics, and privacy headers are owned here; the
    permission-filtered response body is built by the T-256 public service.
    """

    sb = await _lookup_public_storyboard(slug, db)
    if sb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not_found",
            headers=_public_headers(),
        )
    # Found + shareable: the allow-list body is service-owned (T-256).
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "storyboard_pipeline_unavailable",
            "component": "public_sharing",
        },
        headers=_public_headers(),
    )


@router.get("/storyboards/public/{slug}/download/{kind}")
async def download_public_storyboard(
    slug: str,
    kind: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Public download, gated by per-Storyboard permissions. Wired in T-256."""

    sb = await _lookup_public_storyboard(slug, db)
    if sb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not_found",
            headers=_public_headers(),
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "storyboard_pipeline_unavailable",
            "component": "public_sharing",
        },
        headers=_public_headers(),
    )

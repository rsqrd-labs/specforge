"""Storyboard owner and public API router (Phase 20 — T-251).

This module owns the Storyboard HTTP contract: route registration, auth and
ownership boundaries, CSRF posture, response shapes, public privacy headers, and
download streaming semantics. The business logic is delegated to services:

* generation / regeneration / section regen  -> T-254 storyboard_service
* HTML and PDF rendered downloads             -> T-255 storyboard_renderer
* public allow-list response + slug/share     -> T-256 storyboard_public_service

Owner reads, generation, all owner download/render surfaces, owner share
management, and the unauthenticated public view/downloads are all wired here.

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

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db, get_redis
from middleware.auth import get_current_user
from models import Storyboard, User, Workspace
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
from services.credit_service import InsufficientCreditsError
from services.pipeline import storyboard_public_service, storyboard_renderer
from services.pipeline.storyboard_service import (
    COST_FULL_GENERATION,
    COST_SECTION_REGENERATION,
    StoryboardGenerationError,
    StoryboardNotFoundError,
    StoryboardNotPresentableError,
    StoryboardSectionNotFoundError,
)
from services.pipeline.storyboard_service import (
    generate_storyboard as _service_generate_storyboard,
)
from services.pipeline.storyboard_service import (
    regenerate_section as _service_regenerate_section,
)
from services.pipeline.storyboard_service import (
    regenerate_storyboard as _service_regenerate_storyboard,
)
from services.pipeline.storyboard_source import (
    StoryboardStagesNotFinalisedError,
    StoryboardWorkspaceNotFoundError,
)
from services.workspace_service import workspace_service

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


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="not_found",
    )


def _stages_not_finalised(exc: StoryboardStagesNotFinalisedError) -> HTTPException:
    """409: the workspace's source stages are not all finalised.

    Surfaces which stages are not ready (status only — never any content) so the
    UI can guide the owner without leaking artifact text.
    """

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "storyboard_stages_not_finalised",
            "stages": exc.not_ready,
        },
    )


def _insufficient_credits(required: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={"code": "insufficient_credits", "required": required},
    )


def _generation_failed(exc: StoryboardGenerationError) -> HTTPException:
    """502: generation failed after the debit; the credit was already refunded.

    ``detail`` is the redaction-safe, content-free reason carried by the typed
    service error — never raw generated text.
    """

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "storyboard_generation_failed",
            "error_type": exc.error_type,
            "reason": exc.detail,
        },
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


async def _workspace_name(workspace_id: UUID, db: AsyncSession) -> str:
    """Workspace name for filename slugging, or "" (renderer falls back safely).

    A scalar column read — ownership was already proven by the Storyboard lookup,
    and the name only feeds the download filename, never the response body.
    """

    result = await db.execute(
        select(Workspace.name).where(Workspace.id == workspace_id)
    )
    name = result.scalar_one_or_none()
    return name if isinstance(name, str) else ""


def _require_presentable(sb: Storyboard) -> None:
    """Reject downloads/renders of a non-presentable version (no content yet)."""

    if sb.status not in _PRESENTABLE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "storyboard_not_ready"},
        )


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
    redis: Redis = Depends(get_redis),
) -> StoryboardDetail:
    """Generate a new Storyboard from the workspace's finalised stages (25 credits).

    Ownership is validated up front so an unauthorised caller gets 404 before any
    pipeline work; the service then runs source extraction, the debit, the LLM
    call, and strict validation with idempotent, refund-safe semantics (T-254).
    """

    await workspace_service.get(id, user.id, db)
    try:
        sb = await _service_generate_storyboard(db, redis, id, user.id)
    except (StoryboardWorkspaceNotFoundError, StoryboardNotFoundError) as exc:
        raise _not_found() from exc
    except StoryboardStagesNotFinalisedError as exc:
        raise _stages_not_finalised(exc) from exc
    except InsufficientCreditsError as exc:
        raise _insufficient_credits(COST_FULL_GENERATION) from exc
    except StoryboardGenerationError as exc:
        raise _generation_failed(exc) from exc
    return _detail(sb)


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
    redis: Redis = Depends(get_redis),
) -> StoryboardDetail:
    """Full regeneration into a new version (25 credits).

    The previous ready version is never mutated: a new version row is created, so
    if this regeneration fails the prior keynote remains the latest presentable
    one.
    """

    await _get_owned_storyboard(id, user, db)
    try:
        sb = await _service_regenerate_storyboard(db, redis, id, user.id)
    except StoryboardNotFoundError as exc:
        raise _not_found() from exc
    except StoryboardStagesNotFinalisedError as exc:
        raise _stages_not_finalised(exc) from exc
    except InsufficientCreditsError as exc:
        raise _insufficient_credits(COST_FULL_GENERATION) from exc
    except StoryboardGenerationError as exc:
        raise _generation_failed(exc) from exc
    return _detail(sb)


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
    redis: Redis = Depends(get_redis),
) -> StoryboardDetail:
    """Regenerate a single section into a new version (5 credits).

    Only the named act is replaced; everything else is carried over from the
    base version and the spliced payload is re-validated as a whole before
    persistence. A failure leaves the base version's section active.
    """

    await _get_owned_storyboard(id, user, db)
    try:
        sb = await _service_regenerate_section(db, redis, id, section_id, user.id)
    except StoryboardNotFoundError as exc:
        raise _not_found() from exc
    except StoryboardSectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "storyboard_section_not_found", "section_id": section_id},
        ) from exc
    except StoryboardNotPresentableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "storyboard_not_ready"},
        ) from exc
    except StoryboardStagesNotFinalisedError as exc:
        raise _stages_not_finalised(exc) from exc
    except InsufficientCreditsError as exc:
        raise _insufficient_credits(COST_SECTION_REGENERATION) from exc
    except StoryboardGenerationError as exc:
        raise _generation_failed(exc) from exc
    return _detail(sb)


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


def _attachment_headers(filename: str, *, csp: str | None = None) -> dict[str, str]:
    """Download headers: force attachment + nosniff, optionally a strict CSP.

    Rendered HTML is always served as an attachment with ``nosniff`` so the API
    origin can never be coaxed into executing the deck inline, and carries the
    same CSP as the template's embedded ``<meta>``.
    """

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    if csp is not None:
        headers["Content-Security-Policy"] = csp
    return headers


@router.get("/storyboards/{id}/download/html")
async def download_storyboard_html(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Offline, self-contained HTML keynote package (owner only).

    Rendered by the trusted renderer; served as an attachment with a strict CSP
    and ``nosniff`` so it cannot execute inline on the API origin.
    """

    sb = await _get_owned_storyboard(id, user, db)
    _require_presentable(sb)
    workspace_name = await _workspace_name(sb.workspace_id, db)
    html = storyboard_renderer.render_deck_html(sb.content_json or {}, workspace_name)
    storyboard_renderer.record_download_event(
        storyboard_id=sb.id,
        workspace_id=sb.workspace_id,
        user_id=user.id,
        version=sb.version,
        kind="html",
        public=False,
        status=sb.status,
    )
    return Response(
        content=html.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers=_attachment_headers(
            storyboard_renderer.filename_for("html", workspace_name),
            csp=storyboard_renderer.HTML_CSP,
        ),
    )


@router.get("/storyboards/{id}/download/pdf")
async def download_storyboard_pdf(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Static PDF keynote, rendered via the shared no-network PDF executor."""

    sb = await _get_owned_storyboard(id, user, db)
    _require_presentable(sb)
    workspace_name = await _workspace_name(sb.workspace_id, db)
    pdf_bytes = await storyboard_renderer.render_deck_pdf(
        sb.content_json or {}, workspace_name
    )
    storyboard_renderer.record_download_event(
        storyboard_id=sb.id,
        workspace_id=sb.workspace_id,
        user_id=user.id,
        version=sb.version,
        kind="pdf",
        public=False,
        status=sb.status,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=_attachment_headers(
            storyboard_renderer.filename_for("pdf", workspace_name)
        ),
    )


@router.get("/storyboards/{id}/download/notes")
async def download_storyboard_notes(
    id: UUID,
    format: StoryboardNotesFormat = Query(default="md"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Speaker notes as raw markdown (default) or a rendered PDF."""

    sb = await _get_owned_storyboard(id, user, db)
    _require_presentable(sb)
    workspace_name = await _workspace_name(sb.workspace_id, db)
    if format == "pdf":
        pdf_bytes = await storyboard_renderer.render_notes_pdf(
            sb.speaker_notes_md, workspace_name
        )
        storyboard_renderer.record_download_event(
            storyboard_id=sb.id,
            workspace_id=sb.workspace_id,
            user_id=user.id,
            version=sb.version,
            kind="notes-pdf",
            public=False,
            status=sb.status,
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=_attachment_headers(
                storyboard_renderer.filename_for("notes-pdf", workspace_name)
            ),
        )
    storyboard_renderer.record_download_event(
        storyboard_id=sb.id,
        workspace_id=sb.workspace_id,
        user_id=user.id,
        version=sb.version,
        kind="notes-md",
        public=False,
        status=sb.status,
    )
    return _markdown_download(
        sb.speaker_notes_md,
        storyboard_renderer.filename_for("notes-md", workspace_name),
        sb.status,
    )


@router.get("/storyboards/{id}/download/demo-script")
async def download_storyboard_demo_script(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    sb = await _get_owned_storyboard(id, user, db)
    _require_presentable(sb)
    workspace_name = await _workspace_name(sb.workspace_id, db)
    storyboard_renderer.record_download_event(
        storyboard_id=sb.id,
        workspace_id=sb.workspace_id,
        user_id=user.id,
        version=sb.version,
        kind="demo-script",
        public=False,
        status=sb.status,
    )
    return _markdown_download(
        sb.demo_script_md,
        storyboard_renderer.filename_for("demo-script", workspace_name),
        sb.status,
    )


@router.get("/storyboards/{id}/download/appendix")
async def download_storyboard_appendix(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    sb = await _get_owned_storyboard(id, user, db)
    _require_presentable(sb)
    workspace_name = await _workspace_name(sb.workspace_id, db)
    storyboard_renderer.record_download_event(
        storyboard_id=sb.id,
        workspace_id=sb.workspace_id,
        user_id=user.id,
        version=sb.version,
        kind="appendix",
        public=False,
        status=sb.status,
    )
    return _markdown_download(
        sb.technical_appendix_md,
        storyboard_renderer.filename_for("appendix", workspace_name),
        sb.status,
    )


# ---------------------------------------------------------------------------
# Owner — public share management
# ---------------------------------------------------------------------------


def _share_url(slug: str) -> str:
    """Absolute public Storyboard URL the frontend surfaces (independent of the
    workspace ``/p/`` share — Storyboards live at ``/sb/{slug}``)."""

    base = settings.frontend_url.rstrip("/")
    return f"{base}/sb/{slug}"


def _share_response(sb: Storyboard) -> StoryboardShareResponse:
    return StoryboardShareResponse(
        slug=sb.public_share_slug or "",
        url=_share_url(sb.public_share_slug) if sb.public_share_slug else "",
        enabled=sb.public_share_enabled,
        permissions=_permissions(sb),
    )


@router.post("/storyboards/{id}/share", response_model=StoryboardShareResponse)
async def enable_storyboard_share(
    id: UUID,
    payload: StoryboardShareRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardShareResponse:
    """Enable public sharing and/or update permissions.

    The service owns the owned-load (so the retry-on-collision path is not
    confused by a second query); a non-owned id is 404, a non-presentable version
    is 409. Permission changes take effect immediately.
    """

    try:
        sb = await storyboard_public_service.enable_share(db, id, user.id, payload)
    except StoryboardNotFoundError as exc:
        raise _not_found() from exc
    except StoryboardNotPresentableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "storyboard_not_ready"},
        ) from exc
    return _share_response(sb)


@router.delete("/storyboards/{id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def disable_storyboard_share(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Disable public sharing; the slug is preserved so re-enable reuses the URL."""

    try:
        await storyboard_public_service.disable_share(db, id, user.id)
    except StoryboardNotFoundError as exc:
        raise _not_found() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/storyboards/{id}/share/rotate", response_model=StoryboardShareResponse)
async def rotate_storyboard_share(
    id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryboardShareResponse:
    """Rotate the public slug, invalidating the old link immediately."""

    try:
        sb = await storyboard_public_service.rotate_share(db, id, user.id)
    except StoryboardNotFoundError as exc:
        raise _not_found() from exc
    except StoryboardNotPresentableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "storyboard_not_ready"},
        ) from exc
    return _share_response(sb)


# ---------------------------------------------------------------------------
# Public — unauthenticated, read-only
# ---------------------------------------------------------------------------


def _public_404() -> HTTPException:
    """404 with the public privacy headers.

    Every public denial — unknown/disabled/rotated slug, a download that isn't
    permitted, or an unknown kind — returns this so existence is never confirmed
    with a forbidden-style response.
    """

    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="not_found",
        headers=_public_headers(),
    )


def _public_attachment_headers(filename: str) -> dict[str, str]:
    """Download headers for a public artifact: attachment + nosniff + the public
    noindex / no-store posture."""

    return {
        **_public_headers(),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }


@router.get("/storyboards/public/{slug}")
async def get_public_storyboard(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Public allow-list view of a shared Storyboard.

    The response body is permission-filtered by the public service and returned
    as a fresh DTO (never the ORM row); privacy headers are applied here.
    """

    sb = await storyboard_public_service.lookup_shareable(db, slug)
    if sb is None:
        raise _public_404()
    view = storyboard_public_service.build_public_view(sb)
    storyboard_public_service.record_public_view(sb)
    return JSONResponse(
        content=view.model_dump(mode="json"),
        headers=_public_headers(),
    )


# Public download kind → (renderer filename kind, markdown attribute). ``pdf`` is
# rendered (no markdown attribute); the offline package kind is intentionally not
# a key here (req 9).
_PUBLIC_MARKDOWN_DOWNLOADS: dict[str, tuple[str, str]] = {
    "notes": ("notes-md", "speaker_notes_md"),
    "demo-script": ("demo-script", "demo_script_md"),
    "appendix": ("appendix", "technical_appendix_md"),
}


@router.get("/storyboards/public/{slug}/download/{kind}")
async def download_public_storyboard(
    slug: str,
    kind: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Public download, gated by per-Storyboard permissions (404 on any denial).

    The filename is slugged from the Storyboard title (never the workspace name)
    so the internal workspace name is not leaked.
    """

    sb = await storyboard_public_service.lookup_shareable(db, slug)
    if sb is None:
        raise _public_404()
    # 404 for unknown kinds and kinds the owner has not enabled.
    if not storyboard_public_service.is_public_download_allowed(sb, kind):
        raise _public_404()

    if kind == "pdf":
        pdf_bytes = await storyboard_renderer.render_deck_pdf(
            sb.content_json or {}, sb.title
        )
        storyboard_renderer.record_download_event(
            storyboard_id=sb.id,
            workspace_id=sb.workspace_id,
            version=sb.version,
            kind="pdf",
            public=True,
            status=sb.status,
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=_public_attachment_headers(
                storyboard_renderer.filename_for("pdf", sb.title)
            ),
        )

    filename_kind, attribute = _PUBLIC_MARKDOWN_DOWNLOADS[kind]
    body: str = getattr(sb, attribute) or ""
    storyboard_renderer.record_download_event(
        storyboard_id=sb.id,
        workspace_id=sb.workspace_id,
        version=sb.version,
        kind=filename_kind,
        public=True,
        status=sb.status,
    )
    return Response(
        content=body.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=_public_attachment_headers(
            storyboard_renderer.filename_for(filename_kind, sb.title)
        ),
    )

"""Storyboard public sharing service and permission filtering (Phase 20 — T-256).

Public Storyboard sharing is independent from workspace public sharing: it lives
on the ``storyboards`` table (its own ``public_share_slug`` / ``public_share_enabled``
columns and the four ``allow_*`` permission toggles) and is surfaced at the
frontend ``/sb/{slug}`` route via the unauthenticated ``/storyboards/public/{slug}``
APIs. A shared Storyboard pins one specific version row; rotating, disabling, and
permission toggles all act on that row.

Privacy model (Storyboard Delivery Directive §7, req 7/8):
- The public response is **allow-list constructed** — ``build_public_view`` copies
  only named fields into a fresh DTO; it never serialises the ORM row or passes
  ``content_json`` through, so a new private column/payload key can never leak by
  default.
- The harness contract binds ``presentation`` to the full ``storyboard-payload``
  schema (every gated field is required and non-empty), so privacy is enforced by
  **redaction, not omission**: gated text (speaker notes, technical appendix,
  source excerpts) is blanked to neutral constants when its permission is off, and
  carries real content only when the owner enables it. Structure (section/slide/
  layer counts, note keys, ≥1 source ref per entry) is always preserved so the
  presentation stays a structurally valid payload either way.
- Unknown / disabled / rotated slugs and unauthorized downloads resolve to 404,
  never 403 — the existence of any private Storyboard is never confirmed.

Slug model (req 2): 16 chars from an opaque base62 alphabet drawn with the
``secrets`` CSPRNG; the partial unique index from T-250 is the uniqueness guard,
with a bounded commit-retry on the (astronomically unlikely) collision.
"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Storyboard
from schemas.storyboard import (
    StoryboardPublicResponse,
    StoryboardSharePermissions,
    StoryboardShareRequest,
)
from services.pipeline.storyboard_service import (
    StoryboardNotFoundError,
    StoryboardNotPresentableError,
)

logger = logging.getLogger(__name__)

# Opaque base62 alphabet (a-zA-Z0-9). 16 chars ≫ the 10-char minimum, drawn with
# the secrets CSPRNG. 62^16 ≈ 4.7e28 so a collision is effectively impossible;
# the partial unique index is the authoritative guard and the retry below is
# defence-in-depth.
_SLUG_ALPHABET = string.ascii_lowercase + string.ascii_uppercase + string.digits
_SLUG_LEN = 16
_MAX_SLUG_ATTEMPTS = 5

_PRESENTABLE = frozenset({"ready", "stale"})

# Public downloads, in display order. HTML is intentionally absent (req 9). This
# tuple is the single source of truth shared by the response ``downloads`` list
# and the per-kind download gate so the two can never drift.
_PUBLIC_DOWNLOAD_ORDER: tuple[str, ...] = ("pdf", "demo-script", "notes", "appendix")

# Neutral, schema-valid constants used to redact gated text when the matching
# permission is off (kept non-empty to satisfy the payload schema's minLength).
_REDACTED_NOTE = "Speaker notes are private for this Storyboard."
_REDACTED_APPENDIX = (
    "The technical appendix is available with the presenter's permission."
)
_REDACTED_EXCERPT = "Source excerpt available with the presenter's permission."
_REDACTED_LINE = "—"


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------


def generate_slug() -> str:
    """One opaque public share slug (req 2: ≥10 chars, CSPRNG, base62)."""

    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(_SLUG_LEN))


# ---------------------------------------------------------------------------
# Owner share lifecycle (enable / disable / rotate)
# ---------------------------------------------------------------------------


async def _load_owned(
    db: AsyncSession, storyboard_id: UUID, user_id: UUID
) -> Storyboard:
    result = await db.execute(
        select(Storyboard).where(
            Storyboard.id == storyboard_id,
            Storyboard.user_id == user_id,
        )
    )
    sb = result.scalar_one_or_none()
    if sb is None:
        raise StoryboardNotFoundError(str(storyboard_id))
    return sb


def _apply_permissions(sb: Storyboard, request: StoryboardShareRequest | None) -> None:
    """Apply only the permission fields the caller set (``None`` = unchanged).

    On first enable with no overrides the columns keep their defaults — PDF on,
    notes/appendix/source layer off (req 3).
    """

    if request is None:
        return
    if request.allow_pdf_download is not None:
        sb.allow_pdf_download = request.allow_pdf_download
    if request.allow_notes_download is not None:
        sb.allow_notes_download = request.allow_notes_download
    if request.allow_appendix_download is not None:
        sb.allow_appendix_download = request.allow_appendix_download
    if request.allow_source_layer is not None:
        sb.allow_source_layer = request.allow_source_layer


async def enable_share(
    db: AsyncSession,
    storyboard_id: UUID,
    user_id: UUID,
    request: StoryboardShareRequest | None = None,
) -> Storyboard:
    """Enable public sharing and/or update permissions for a Storyboard version.

    Idempotent on the slug: a previously-allocated slug is reused on re-enable so
    an existing ``/sb/{slug}`` link keeps working (req 6). Permission changes take
    effect immediately on commit (req 4). Only a presentable version can be
    shared — sharing a failed/generating row would only mint a slug that 404s.
    """

    sb = await _load_owned(db, storyboard_id, user_id)
    if sb.status not in _PRESENTABLE:
        raise StoryboardNotPresentableError(
            f"storyboard {storyboard_id} is not presentable (status={sb.status})"
        )

    # Reuse an existing slug — only flip the flag, apply permissions, touch ts.
    if sb.public_share_slug:
        sb.public_share_enabled = True
        _apply_permissions(sb, request)
        sb.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(sb)
        logger.info(
            "storyboard.share.enabled",
            extra={"storyboard_id": str(storyboard_id), "rotated": False},
        )
        return sb

    # First share: allocate a unique slug, retrying on the partial-index conflict.
    for attempt in range(_MAX_SLUG_ATTEMPTS):
        sb.public_share_slug = generate_slug()
        sb.public_share_enabled = True
        _apply_permissions(sb, request)
        sb.updated_at = datetime.now(UTC)
        try:
            await db.commit()
            await db.refresh(sb)
            logger.info(
                "storyboard.share.enabled",
                extra={"storyboard_id": str(storyboard_id), "rotated": False},
            )
            return sb
        except IntegrityError:
            await db.rollback()
            logger.warning(
                "storyboard.share.slug_collision",
                extra={"storyboard_id": str(storyboard_id), "attempt": attempt + 1},
            )
            sb = await _load_owned(db, storyboard_id, user_id)
    raise RuntimeError(
        "Could not allocate a unique Storyboard public share slug after "
        f"{_MAX_SLUG_ATTEMPTS} attempts."
    )


async def disable_share(db: AsyncSession, storyboard_id: UUID, user_id: UUID) -> None:
    """Turn public sharing off; the slug is preserved so re-enable reuses it.

    The lookup will now return None → 404 (req 6). A subsequent ``rotate`` is what
    permanently retires the old slug.
    """

    sb = await _load_owned(db, storyboard_id, user_id)
    sb.public_share_enabled = False
    sb.updated_at = datetime.now(UTC)
    await db.commit()
    logger.info(
        "storyboard.share.disabled", extra={"storyboard_id": str(storyboard_id)}
    )


async def rotate_share(
    db: AsyncSession, storyboard_id: UUID, user_id: UUID
) -> Storyboard:
    """Atomically retire the old slug and mint a new one, leaving sharing enabled.

    Rotation is a single committed slug replacement, so the old ``/sb/{slug}``
    link 404s the instant the new slug commits (req 5).
    """

    sb = await _load_owned(db, storyboard_id, user_id)
    if sb.status not in _PRESENTABLE:
        raise StoryboardNotPresentableError(
            f"storyboard {storyboard_id} is not presentable (status={sb.status})"
        )

    for attempt in range(_MAX_SLUG_ATTEMPTS):
        candidate = generate_slug()
        if candidate == sb.public_share_slug:
            continue
        sb.public_share_slug = candidate
        sb.public_share_enabled = True
        sb.updated_at = datetime.now(UTC)
        try:
            await db.commit()
            await db.refresh(sb)
            logger.info(
                "storyboard.share.rotated",
                extra={"storyboard_id": str(storyboard_id)},
            )
            return sb
        except IntegrityError:
            await db.rollback()
            logger.warning(
                "storyboard.share.slug_collision",
                extra={"storyboard_id": str(storyboard_id), "attempt": attempt + 1},
            )
            sb = await _load_owned(db, storyboard_id, user_id)
    raise RuntimeError("Could not rotate to a new unique Storyboard slug.")


async def lookup_shareable(db: AsyncSession, slug: str) -> Storyboard | None:
    """Resolve a shareable Storyboard by slug, or None (→ 404).

    Returns None for unknown, disabled, rotated, or non-presentable slugs so the
    existence of any private Storyboard is never leaked. A rotated slug no longer
    matches any row; a disabled one fails the ``public_share_enabled`` filter.
    """

    if not slug:
        return None
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


# ---------------------------------------------------------------------------
# Permission matrix (single source of truth for the downloads list + the gate)
# ---------------------------------------------------------------------------


def is_public_download_allowed(sb: Storyboard, kind: str) -> bool:
    """Whether *kind* may be downloaded publicly for this Storyboard.

    HTML is never public (req 9); unknown kinds are denied. ``demo-script`` is
    available whenever the Storyboard is shared (req 8).
    """

    if kind == "pdf":
        return bool(sb.allow_pdf_download)
    if kind == "notes":
        return bool(sb.allow_notes_download)
    if kind == "appendix":
        return bool(sb.allow_appendix_download)
    if kind == "demo-script":
        return True
    return False


def available_public_downloads(sb: Storyboard) -> list[str]:
    """The public download kinds currently enabled, in display order."""

    return [k for k in _PUBLIC_DOWNLOAD_ORDER if is_public_download_allowed(sb, k)]


def permissions_of(sb: Storyboard) -> StoryboardSharePermissions:
    return StoryboardSharePermissions(
        allow_pdf_download=sb.allow_pdf_download,
        allow_notes_download=sb.allow_notes_download,
        allow_appendix_download=sb.allow_appendix_download,
        allow_source_layer=sb.allow_source_layer,
    )


# ---------------------------------------------------------------------------
# Allow-list public presentation
# ---------------------------------------------------------------------------


def _public_source_ref(ref: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
    """One allow-listed source ref.

    When the source layer is off we blank *both* the excerpt and the source_id:
    the enum ``source`` (SPEC/PLAN/…) is already public via ``slide.sources`` and
    is schema-required, but the section-level ``source_id`` and the verbatim
    excerpt are part of the gated source-attribution layer, so neither is exposed
    until the owner enables it.
    """

    if reveal:
        return {
            "source": ref.get("source", "SPEC"),
            "source_id": ref.get("source_id", ""),
            "excerpt": ref.get("excerpt", ""),
        }
    return {
        "source": ref.get("source", "SPEC"),
        "source_id": _REDACTED_LINE,
        "excerpt": _REDACTED_EXCERPT,
    }


def _public_slide(slide: dict[str, Any]) -> dict[str, Any]:
    visual = slide.get("visual") or {}
    # Visual is an inert layout descriptor (extra keys allowed by the schema); we
    # copy it wholesale — it carries no account data and the renderer never
    # interprets any value as markup.
    return {
        "id": slide.get("id", ""),
        "type": slide.get("type", "thesis"),
        "headline": slide.get("headline", ""),
        "visible_text": slide.get("visible_text", ""),
        "visual": dict(visual),
        "speaker_notes_ref": slide.get("speaker_notes_ref", ""),
        # Attribution labels (SPEC/PLAN/…) are required, non-secret, and not
        # excerpts — always real (req schema).
        "sources": list(slide.get("sources") or []),
    }


def _public_note(note: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
    if reveal:
        return {
            "slide_id": note.get("slide_id", ""),
            "talk_track": note.get("talk_track", ""),
            "transition": note.get("transition", ""),
            "timing_seconds": note.get("timing_seconds", 5),
            "pause_cue": note.get("pause_cue", ""),
            "demo_cue": note.get("demo_cue", ""),
            "backup_points": list(note.get("backup_points") or []),
        }
    # Redacted: preserve the key and structure, blank the text. timing is kept
    # (not secret); backup_points → [] dodges the per-item minLength.
    return {
        "slide_id": note.get("slide_id", ""),
        "talk_track": _REDACTED_NOTE,
        "transition": _REDACTED_LINE,
        "timing_seconds": note.get("timing_seconds", 5),
        "pause_cue": _REDACTED_LINE,
        "demo_cue": "",
        "backup_points": [],
    }


def build_public_presentation(
    content: dict[str, Any] | None, permissions: StoryboardSharePermissions
) -> dict[str, Any]:
    """Build the permission-filtered ``presentation`` payload (allow-list).

    Always a structurally complete ``storyboard-payload``: the visual deck (title,
    theme, sections, diagram structure, demo script) is always real; speaker
    notes, the technical appendix, and source excerpts are real only when their
    permission is on and are otherwise blanked to neutral constants.
    """

    content = content or {}
    theme = content.get("theme") or {}
    reveal_notes = permissions.allow_notes_download
    reveal_appendix = permissions.allow_appendix_download
    reveal_sources = permissions.allow_source_layer

    sections = [
        {
            "id": section.get("id", ""),
            "title": section.get("title", ""),
            "slides": [_public_slide(s) for s in (section.get("slides") or [])],
        }
        for section in (content.get("sections") or [])
    ]

    diagrams = [
        {
            "id": diagram.get("id", ""),
            "type": diagram.get("type", ""),
            "layers": [
                {
                    "id": layer.get("id", ""),
                    "kind": layer.get("kind", "group"),
                    "label": layer.get("label", ""),
                    "summary": layer.get("summary", ""),
                    "source_refs": [
                        _public_source_ref(ref, reveal=reveal_sources)
                        for ref in (layer.get("source_refs") or [])
                    ],
                }
                for layer in (diagram.get("layers") or [])
            ],
        }
        for diagram in (content.get("diagrams") or [])
    ]

    source_map = {
        key: [_public_source_ref(ref, reveal=reveal_sources) for ref in refs]
        for key, refs in (content.get("source_map") or {}).items()
    }

    notes = {
        slide_id: _public_note(note, reveal=reveal_notes)
        for slide_id, note in (content.get("notes") or {}).items()
    }

    return {
        "title": content.get("title", ""),
        "theme": {
            "palette": list(theme.get("palette") or []),
            "typography": theme.get("typography", ""),
            "motif": theme.get("motif", ""),
            "transition_style": theme.get("transition_style", ""),
            "diagram_style": theme.get("diagram_style", ""),
        },
        "sections": sections,
        "diagrams": diagrams,
        "source_map": source_map,
        "notes": notes,
        # Demo script is a public deliverable when shared (not in the req-7
        # exclusion list) — always real.
        "demo_script_md": content.get("demo_script_md", ""),
        "technical_appendix_md": (
            content.get("technical_appendix_md", "")
            if reveal_appendix
            else _REDACTED_APPENDIX
        ),
    }


def build_public_view(sb: Storyboard) -> StoryboardPublicResponse:
    """Assemble the allow-listed public response DTO for a shareable Storyboard.

    Returns a DTO, never the ORM row. ``shared_at`` uses ``updated_at`` (there is
    no dedicated ``public_shared_at`` column on the Storyboard model); note that a
    later stale-propagation that bumps ``updated_at`` can therefore move
    ``shared_at`` — acceptable, and out of scope to add a column here.
    """

    permissions = permissions_of(sb)
    return StoryboardPublicResponse(
        title=sb.title,
        presentation=build_public_presentation(sb.content_json, permissions),
        permissions=permissions,
        downloads=available_public_downloads(sb),
        shared_at=sb.updated_at,
    )

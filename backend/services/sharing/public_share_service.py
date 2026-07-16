"""Public share lifecycle — enable / disable / rotate + public view assembly.

T-USE-09 / T-168. The three lifecycle entry points (`enable`, `disable`,
`rotate`) maintain the workspace's `public_share_slug`, `public_share_enabled`,
and `public_shared_at` columns. `build_public_view` is the ONLY function
that constructs the public response — every public field passes through
its allow-list so future ORM additions cannot silently leak.

Security:
- Slug generation uses the `secrets` module (CSPRNG), never `random`.
- Slug alphabet omits ambiguous characters (0/o/1/l/i) so users can read
  the URL off a screen without confusion (Plan §18.3).
- Enable refuses to open a workspace with any non-finalised stage.
- The response shape is locked by Pydantic `extra="forbid"`; adding a new
  field is an explicit privacy decision.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import Stage, Workspace
from schemas.workspace import (
    PublicStageView,
    PublicWorkspaceResponse,
)
from services.coverage_utils import derive_coverage_summary

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# 31-character alphabet — no ambiguous chars (0/o/1/l/i are intentionally
# excluded so the slug can be read off a screen and re-typed without confusion).
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
# 16 chars over the 31-char alphabet ≈ 31^16 ≈ 2^79 of entropy — unguessable and
# infeasible to bulk-harvest even behind the per-IP public-view rate tier. Raised
# from 6 (≈2^30) to close the share-slug entropy finding and match the storyboard
# public-share sibling's 16-char length. Existing shorter slugs stay valid
# (`is_valid_slug` is length-agnostic under its ceiling); only new slugs are longer.
SLUG_LEN = 16
# Hard ceiling on an accepted slug length. Real slugs are exactly SLUG_LEN; the
# ceiling only bounds the DB/Redis-key surface an arbitrary-slug scraper can probe
# on the unauthenticated read path (no legitimate slug approaches it).
_MAX_SLUG_LEN = 64
_MAX_GENERATE_ATTEMPTS = 3
_STAGE_ORDER: tuple[str, ...] = ("spec", "plan", "harness", "tasks")


class WorkspaceNotFinalisedError(Exception):
    """Raised by `enable` when any of the four stages isn't finalised yet."""


class WorkspaceNotFoundError(Exception):
    """Raised when the workspace row doesn't exist for the caller."""


def _generate_slug() -> str:
    """Generate one fresh slug from the unambiguous alphabet using CSPRNG."""
    return "".join(secrets.choice(ALPHABET) for _ in range(SLUG_LEN))


def is_valid_slug(slug: str) -> bool:
    """True when ``slug`` is shaped like a real share slug (alphabet only).

    Used to gate DB/Redis work on the unauthenticated read path before either is
    touched, so an arbitrary-slug scraper can neither hit the pool nor pollute the
    Redis cache key space with junk keys.
    """
    return (
        bool(slug) and len(slug) <= _MAX_SLUG_LEN and all(ch in ALPHABET for ch in slug)
    )


# ---------------------------------------------------------------------------
# Public-view payload cache (scalability audit P2). The unauthenticated
# GET /public/{slug} surface is scraper-exposed; every cache miss runs two DB
# reads + a coverage rollup against the shared pool. A short Redis cache of the
# assembled, allow-listed response keeps a burst off the pool. Positives only are
# cached (never 404s — a memory vector under arbitrary-slug scraping; the alphabet
# gate + the _PUBLIC_VIEW_LIMIT rate tier already bound the negative path), within
# the staleness the response already advertises (Cache-Control max-age=60), and
# the key is evicted on enable/disable/rotate so a just-killed or just-rotated
# share is never served from cache. Every operation fails open: any Redis error
# falls back to the authoritative DB path.
# ---------------------------------------------------------------------------

_PUBLIC_VIEW_CACHE_KEY = "public_view:v2:{slug}"


def _public_cache_key(slug: str) -> str:
    return _PUBLIC_VIEW_CACHE_KEY.format(slug=slug)


def _cache_enabled(redis: "Redis | None") -> bool:
    return redis is not None and settings.public_share_cache_ttl_seconds > 0


async def get_cached_public_payload(
    redis: "Redis | None", slug: str
) -> tuple[str, str] | None:
    """Return the cached ``(etag, json_body)`` for a slug, or None. Fail-open."""
    if not _cache_enabled(redis) or not is_valid_slug(slug):
        return None
    try:
        raw = await redis.get(_public_cache_key(slug))  # type: ignore[union-attr]
    except RedisError:
        logger.warning("public_view_cache.get_failed slug=%s", slug)
        return None
    if not raw:
        return None
    try:
        envelope = json.loads(raw)
        return str(envelope["etag"]), str(envelope["body"])
    except (ValueError, KeyError, TypeError):
        # A malformed/legacy cache entry is treated as a miss (it is rebuilt and
        # overwritten on the read-through below); never serve corrupt bytes.
        return None


async def set_cached_public_payload(
    redis: "Redis | None", slug: str, etag: str, json_body: str
) -> None:
    """Cache the assembled public payload for a slug with the configured TTL."""
    if not _cache_enabled(redis) or not is_valid_slug(slug):
        return
    try:
        await redis.set(  # type: ignore[union-attr]
            _public_cache_key(slug),
            json.dumps({"etag": etag, "body": json_body}),
            ex=settings.public_share_cache_ttl_seconds,
        )
    except RedisError:
        logger.warning("public_view_cache.set_failed slug=%s", slug)


async def evict_cached_public_payload(redis: "Redis | None", slug: str | None) -> None:
    """Drop a slug's cached payload (enable/disable/rotate). Fail-open no-op."""
    if redis is None or not slug:
        return
    try:
        await redis.delete(_public_cache_key(slug))
    except RedisError:
        logger.warning("public_view_cache.evict_failed slug=%s", slug)


async def _load_workspace(workspace_id: UUID, db: AsyncSession) -> Workspace:
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise WorkspaceNotFoundError(str(workspace_id))
    return workspace


async def _load_stages(workspace_id: UUID, db: AsyncSession) -> dict[str, Stage]:
    result = await db.execute(select(Stage).where(Stage.workspace_id == workspace_id))
    return {s.type: s for s in result.scalars()}


async def _assert_all_finalised(workspace_id: UUID, db: AsyncSession) -> None:
    stages = await _load_stages(workspace_id, db)
    for stage_type in _STAGE_ORDER:
        stage = stages.get(stage_type)
        if stage is None or stage.status != "finalised":
            raise WorkspaceNotFinalisedError(
                f"Stage {stage_type!r} is not finalised — public share unavailable"
            )


async def enable(
    workspace_id: UUID, db: AsyncSession, redis: "Redis | None" = None
) -> str:
    """Turn public sharing on. Idempotent: reuses the existing slug.

    Raises WorkspaceNotFinalisedError if any of the four stages is not
    finalised yet (Spec §4.8). Evicts any stale cached payload for the slug so a
    re-enable (which bumps ``public_shared_at`` and therefore the ETag) is never
    served from a prior-period cache entry.
    """
    await _assert_all_finalised(workspace_id, db)
    workspace = await _load_workspace(workspace_id, db)

    if workspace.public_share_slug:
        # Idempotent reuse — only flip the flag and bump the timestamp.
        workspace.public_share_enabled = True
        workspace.public_shared_at = datetime.now(timezone.utc)
        await db.commit()
        await evict_cached_public_payload(redis, workspace.public_share_slug)
        return workspace.public_share_slug

    # No slug yet — generate one, retrying on the (rare) partial-index conflict.
    for attempt in range(_MAX_GENERATE_ATTEMPTS):
        candidate = _generate_slug()
        workspace.public_share_slug = candidate
        workspace.public_share_enabled = True
        workspace.public_shared_at = datetime.now(timezone.utc)
        try:
            await db.commit()
            await evict_cached_public_payload(redis, candidate)
            return candidate
        except IntegrityError:
            await db.rollback()
            logger.warning(
                "public_share_slug_collision attempt=%d workspace_id=%s",
                attempt + 1,
                workspace_id,
            )
            # Re-fetch on next iteration since the rollback detached the row.
            workspace = await _load_workspace(workspace_id, db)
    raise RuntimeError(
        "Could not allocate a unique public share slug after "
        f"{_MAX_GENERATE_ATTEMPTS} attempts — alphabet space exhausted?"
    )


async def disable(
    workspace_id: UUID, db: AsyncSession, redis: "Redis | None" = None
) -> None:
    """Turn public sharing off but keep the slug so re-enable reuses the URL.

    Evicts the cached payload immediately so a just-disabled share stops being
    served from cache at once, rather than lingering for the cache TTL.
    """
    workspace = await _load_workspace(workspace_id, db)
    slug = workspace.public_share_slug
    workspace.public_share_enabled = False
    await db.commit()
    await evict_cached_public_payload(redis, slug)


async def rotate(
    workspace_id: UUID, db: AsyncSession, redis: "Redis | None" = None
) -> str:
    """Invalidate the old slug and generate a fresh one. Re-enables sharing.

    Evicts the OLD slug's cached payload so the retired URL stops resolving from
    cache immediately (the new slug has no entry yet).
    """
    await _assert_all_finalised(workspace_id, db)
    workspace = await _load_workspace(workspace_id, db)
    old_slug = workspace.public_share_slug
    for attempt in range(_MAX_GENERATE_ATTEMPTS):
        candidate = _generate_slug()
        if candidate == workspace.public_share_slug:
            # Astronomically unlikely but cheap to guard against.
            continue
        workspace.public_share_slug = candidate
        workspace.public_share_enabled = True
        workspace.public_shared_at = datetime.now(timezone.utc)
        try:
            await db.commit()
            await evict_cached_public_payload(redis, old_slug)
            return candidate
        except IntegrityError:
            await db.rollback()
            logger.warning(
                "public_share_rotate_collision attempt=%d workspace_id=%s",
                attempt + 1,
                workspace_id,
            )
            workspace = await _load_workspace(workspace_id, db)
    raise RuntimeError("Could not rotate to a new unique slug")


async def build_public_view(
    slug: str, db: AsyncSession
) -> PublicWorkspaceResponse | None:
    """Assemble the allow-listed public-view response, or None if hidden.

    Returns None for: unknown slugs, slugs whose `public_share_enabled` is
    false, and workspaces whose stages have rolled back below `finalised`
    since enable. The caller should map None → 404.
    """
    if not is_valid_slug(slug):
        return None

    result = await db.execute(
        select(Workspace).where(
            Workspace.public_share_slug == slug,
            Workspace.public_share_enabled.is_(True),
        )
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        return None

    stages = await _load_stages(workspace.id, db)
    stage_views: list[PublicStageView] = []
    for stage_type in _STAGE_ORDER:
        stage = stages.get(stage_type)
        if stage is None or stage.status != "finalised":
            # Owner rolled a stage back after sharing — treat as if disabled
            # so the public viewer doesn't see a partial / inconsistent spec.
            return None
        stage_views.append(
            PublicStageView(type=stage_type, content=stage.content or "")
        )

    shared_at = workspace.public_shared_at or workspace.updated_at
    # derive_coverage_summary imported from the shared coverage_utils module
    # so the public view carries the same chip as the in-app workspace response.
    # MF-2 — T-206.
    coverage_summary = await derive_coverage_summary(workspace.id, db)

    # eval_summary stays None for now — the public view's chip uses the
    # coverage_summary as its primary social proof signal.
    return PublicWorkspaceResponse(
        name=workspace.name,
        stages=stage_views,
        coverage_summary=coverage_summary,
        eval_summary=None,
        shared_at=shared_at,
    )

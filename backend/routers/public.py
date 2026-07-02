"""Unauthenticated read-only router for /public/{slug}.

T-USE-09 / T-168. Built so an anonymous viewer can read a published spec
without an account. Defence-in-depth:

- Response body is built via `build_public_view`, which uses the
  PublicWorkspaceResponse Pydantic model (`extra="forbid"`). Adding a new
  field to the public surface is an explicit privacy review item.
- Response headers set `X-Robots-Tag: noindex, nofollow` so crawlers
  ignore the page even if the frontend misses its meta tag.
- ETag from `shared_at` enables If-None-Match → 304 short-circuit.
- Cache-Control allows brief CDN caching but bumps on enable/rotate.
- The auth middleware does not protect this router; the route prefix is
  in the documented exemption list.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, get_redis
from routers.workspace import _PUBLIC_SHARE_CSP
from schemas.workspace import PublicWorkspaceResponse
from services.sharing import public_share_service

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])

_NOINDEX_HEADER = "noindex, nofollow"
_CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=600"


def _etag_for(response: PublicWorkspaceResponse) -> str:
    """Derive a stable, cheap ETag from the `shared_at` bumper."""
    digest = hashlib.sha256(response.shared_at.isoformat().encode("utf-8")).hexdigest()[
        :16
    ]
    return f'W/"{digest}"'


def _headers(etag: str) -> dict[str, str]:
    return {
        "ETag": etag,
        "X-Robots-Tag": _NOINDEX_HEADER,
        "Cache-Control": _CACHE_CONTROL,
        "Content-Security-Policy": _PUBLIC_SHARE_CSP,
    }


def _render(request: Request, etag: str, body: str) -> Response:
    """Build the 304 (If-None-Match hit) or 200 response from etag + JSON body."""
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED, headers=_headers(etag)
        )
    return Response(content=body, media_type="application/json", headers=_headers(etag))


@router.get("/{slug}", response_model=PublicWorkspaceResponse)
async def get_public_workspace(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: "Redis" = Depends(get_redis),
) -> Response:
    # Validate the slug shape before any Redis/DB work so an arbitrary-slug
    # scraper neither hits the pool nor pollutes the cache key space.
    if not public_share_service.is_valid_slug(slug):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    # Cache read-through (scalability audit P2): a short Redis cache of the
    # assembled payload keeps a burst of public/scraper traffic off the shared
    # Postgres pool. Positives only are cached; a hit serves the stored etag+body
    # directly (no DB read). Fail-open — a Redis miss/error falls to the DB build.
    cached = await public_share_service.get_cached_public_payload(redis, slug)
    if cached is not None:
        etag, body = cached
        return _render(request, etag, body)

    view = await public_share_service.build_public_view(slug, db)
    if view is None:
        # Same 404 for unknown / disabled / rolled-back; do not leak which.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    etag = _etag_for(view)
    body = view.model_dump_json()
    await public_share_service.set_cached_public_payload(redis, slug, etag, body)
    return _render(request, etag, body)

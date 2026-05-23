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

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from routers.workspace import _PUBLIC_SHARE_CSP
from schemas.workspace import PublicWorkspaceResponse
from services.sharing import public_share_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])

_NOINDEX_HEADER = "noindex, nofollow"
_CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=600"


def _etag_for(response: PublicWorkspaceResponse) -> str:
    """Derive a stable, cheap ETag from the `shared_at` bumper."""
    digest = hashlib.sha256(
        response.shared_at.isoformat().encode("utf-8")
    ).hexdigest()[:16]
    return f'W/"{digest}"'


@router.get("/{slug}", response_model=PublicWorkspaceResponse)
async def get_public_workspace(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    view = await public_share_service.build_public_view(slug, db)
    if view is None:
        # Same 404 for unknown / disabled / rolled-back; do not leak which.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    etag = _etag_for(view)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                "X-Robots-Tag": _NOINDEX_HEADER,
                "Cache-Control": _CACHE_CONTROL,
                "Content-Security-Policy": _PUBLIC_SHARE_CSP,
            },
        )

    return Response(
        content=view.model_dump_json(),
        media_type="application/json",
        headers={
            "ETag": etag,
            "X-Robots-Tag": _NOINDEX_HEADER,
            "Cache-Control": _CACHE_CONTROL,
            "Content-Security-Policy": _PUBLIC_SHARE_CSP,
        },
    )

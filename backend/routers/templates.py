"""Unauthenticated GET /templates — starter templates strip data source.

T-USE-11 / T-170. Templates are system-owned in V1; this router exposes
the active set ordered by sort_order so the dashboard strip is stable
across deploys. Inactive templates are hidden but kept in the table for
historical Workspace.template_slug references — never delete.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Template
from schemas.template import TemplateRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateRead])
async def list_templates(
    db: AsyncSession = Depends(get_db),
) -> list[TemplateRead]:
    """Return active starter templates ordered by `sort_order`, then `name`.

    Unauthenticated by design — the strip is shown on the landing page
    before the user signs in. No personal data is returned; templates
    are system-owned.
    """
    result = await db.execute(
        select(Template)
        .where(Template.active.is_(True))
        .order_by(Template.sort_order.asc(), Template.name.asc())
    )
    rows = result.scalars().all()
    return [TemplateRead.model_validate(row) for row in rows]

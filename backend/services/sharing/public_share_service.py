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

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Stage, Workspace
from schemas.workspace import (
    PublicStageView,
    PublicWorkspaceResponse,
)
from services.coverage_utils import derive_coverage_summary

logger = logging.getLogger(__name__)

_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic Claude",
    "openai": "OpenAI",
    "google": "Google Gemini",
}


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider or "Unknown")


# 31-character alphabet — no ambiguous chars (0/o/1/l/i are intentionally
# excluded so the slug can be read off a screen and re-typed without confusion).
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SLUG_LEN = 6
_MAX_GENERATE_ATTEMPTS = 3
_STAGE_ORDER: tuple[str, ...] = ("spec", "plan", "harness", "tasks")


class WorkspaceNotFinalisedError(Exception):
    """Raised by `enable` when any of the four stages isn't finalised yet."""


class WorkspaceNotFoundError(Exception):
    """Raised when the workspace row doesn't exist for the caller."""


def _generate_slug() -> str:
    """Generate one fresh slug from the unambiguous alphabet using CSPRNG."""
    return "".join(secrets.choice(ALPHABET) for _ in range(SLUG_LEN))


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


async def enable(workspace_id: UUID, db: AsyncSession) -> str:
    """Turn public sharing on. Idempotent: reuses the existing slug.

    Raises WorkspaceNotFinalisedError if any of the four stages is not
    finalised yet (Spec §4.8).
    """
    await _assert_all_finalised(workspace_id, db)
    workspace = await _load_workspace(workspace_id, db)

    if workspace.public_share_slug:
        # Idempotent reuse — only flip the flag and bump the timestamp.
        workspace.public_share_enabled = True
        workspace.public_shared_at = datetime.now(timezone.utc)
        await db.commit()
        return workspace.public_share_slug

    # No slug yet — generate one, retrying on the (rare) partial-index conflict.
    for attempt in range(_MAX_GENERATE_ATTEMPTS):
        candidate = _generate_slug()
        workspace.public_share_slug = candidate
        workspace.public_share_enabled = True
        workspace.public_shared_at = datetime.now(timezone.utc)
        try:
            await db.commit()
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


async def disable(workspace_id: UUID, db: AsyncSession) -> None:
    """Turn public sharing off but keep the slug so re-enable reuses the URL."""
    workspace = await _load_workspace(workspace_id, db)
    workspace.public_share_enabled = False
    await db.commit()


async def rotate(workspace_id: UUID, db: AsyncSession) -> str:
    """Invalidate the old slug and generate a fresh one. Re-enables sharing."""
    await _assert_all_finalised(workspace_id, db)
    workspace = await _load_workspace(workspace_id, db)
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
    if not slug or not all(ch in ALPHABET for ch in slug):
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
        provider_label=_provider_label(workspace.provider),
        stages=stage_views,
        coverage_summary=coverage_summary,
        eval_summary=None,
        shared_at=shared_at,
    )

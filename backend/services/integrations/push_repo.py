"""Repository helpers for :class:`IntegrationPush` lookups (Phase 21 — T-266).

The "live push" for a repo is the single non-``failed`` :class:`IntegrationPush`
row for a ``(workspace_id, repo_id)`` pair. Migration ``0016`` enforces this with
the partial unique index ``uq_integration_push_workspace_repo_active`` keyed on
``(workspace_id, repo_id) WHERE status <> 'failed'`` — so at most one such row
can exist.

This module is the **single place** the ``status <> 'failed'`` definition is
expressed in query form. Every consumer that needs "the active push" — reconcile
(T-272), drift/sync (T-273), and re-export (T-269/T-276) — must go through
:func:`find_live_push` rather than writing its own predicate, so the rule cannot
drift back into a ``status = 'active'`` query (there is no ``'active'`` status
literal; the enum is ``pending``/``completed``/``failed``/``stale``).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_push import IntegrationPush

# The canonical "live push" predicate, mirroring the partial unique index
# predicate in migration 0016 (``status <> 'failed'``). Kept here, and only here,
# so the definition lives in exactly one place.
_NON_FAILED_STATUS = "failed"


async def find_live_push(
    db: AsyncSession,
    workspace_id: UUID,
    repo_id: int,
) -> IntegrationPush | None:
    """Return the single live (non-``failed``) push for a repo, or ``None``.

    The partial unique index guarantees at most one non-``failed`` row per
    ``(workspace_id, repo_id)``, so this resolves to a single row or nothing.

    ``repo_id`` is GitHub's immutable numeric repository id — the reconciliation
    key — never the mutable ``repo_full_name``.
    """
    result = await db.execute(
        select(IntegrationPush).where(
            IntegrationPush.workspace_id == workspace_id,
            IntegrationPush.repo_id == repo_id,
            IntegrationPush.status != _NON_FAILED_STATUS,
        )
    )
    return result.scalar_one_or_none()

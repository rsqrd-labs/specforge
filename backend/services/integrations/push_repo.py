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

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.github_installation import GitHubInstallation
from models.integration_push import IntegrationPush
from models.integration_push_task import IntegrationPushTask
from models.stage_version import StageVersion
from models.workspace import Workspace
from services.integrations.task_parser import compute_task_ref, parse_tasks

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


async def find_live_pushes_for_event(
    db: AsyncSession,
    repo_id: int,
    installation_id: int,
) -> Sequence[IntegrationPush]:
    """Return the live pushes a GitHub webhook delivery may mutate.

    The confused-deputy guard (spec §12): a delivery for ``repo_id`` may only
    touch pushes whose recorded :class:`GitHubInstallation` matches the
    delivery's own ``installation.id`` (``installation_id`` here is GitHub's
    numeric id from the payload). An event from install A can never reach a push
    under install B, even for the same repo.

    Unlike :func:`find_live_push`, this is **not** keyed on the full
    ``(workspace_id, repo_id)`` unique tuple — two workspaces may export to the
    same repo under the same installation — so it returns *all* matching live
    pushes (zero ⇒ not ours, ignore). Callers iterate; never assume one row.
    """
    result = await db.execute(
        select(IntegrationPush)
        .join(
            GitHubInstallation,
            IntegrationPush.installation_id == GitHubInstallation.id,
        )
        .where(
            IntegrationPush.repo_id == repo_id,
            IntegrationPush.status != _NON_FAILED_STATUS,
            GitHubInstallation.installation_id == installation_id,
        )
    )
    return result.scalars().all()


@dataclass
class LiveExportRow:
    """One row of the account-wide exports hub feed (see
    :func:`list_user_live_exports`): a live push plus the display name of its
    workspace and the issue-completion counts, resolved together so the router
    never issues a per-push follow-up query."""

    push: IntegrationPush
    workspace_name: str
    total: int
    shipped: int


async def list_user_live_exports(
    db: AsyncSession,
    user_id: UUID,
) -> list[LiveExportRow]:
    """Return the caller's live (non-``failed``) GitHub exports, one row per
    workspace, newest-first — the feed for the account-wide exports hub.

    A workspace may accumulate several non-``failed`` push rows over its life
    (e.g. an increment push layered on the baseline); ``DISTINCT ON`` keeps the
    newest per workspace, mirroring :func:`find_workspace_live_push`'s
    newest-first resolution so the hub row and the per-workspace ``/sync`` detail
    agree on *which* push is "the" export. Archived/trashed workspaces are
    excluded (``status = 'active'``). Two queries only: the pushes, then a single
    grouped count over all their task rows — never N+1.
    """
    push_rows = (
        await db.execute(
            select(IntegrationPush, Workspace.name)
            .join(Workspace, IntegrationPush.workspace_id == Workspace.id)
            .where(
                IntegrationPush.user_id == user_id,
                IntegrationPush.provider == "github",
                IntegrationPush.status != _NON_FAILED_STATUS,
                Workspace.status == "active",
            )
            .distinct(IntegrationPush.workspace_id)
            .order_by(
                IntegrationPush.workspace_id,
                IntegrationPush.created_at.desc(),
            )
        )
    ).all()
    if not push_rows:
        return []

    by_id = {push.id: (push, name) for push, name in push_rows}
    counts = (
        await db.execute(
            select(
                IntegrationPushTask.push_id,
                func.count().label("total"),
                func.count()
                .filter(IntegrationPushTask.state == "done")
                .label("shipped"),
            )
            .where(IntegrationPushTask.push_id.in_(list(by_id)))
            .group_by(IntegrationPushTask.push_id)
        )
    ).all()
    count_map = {pid: (total, shipped) for pid, total, shipped in counts}

    rows = [
        LiveExportRow(
            push=push,
            workspace_name=name,
            total=count_map.get(push.id, (0, 0))[0],
            shipped=count_map.get(push.id, (0, 0))[1],
        )
        for push, name in by_id.values()
    ]
    # Newest export first; a still-pending push has no pushed_at yet, so fall
    # back to created_at for a stable order.
    rows.sort(key=lambda r: (r.push.pushed_at or r.push.created_at), reverse=True)
    return rows


async def resolve_push_task_titles(
    db: AsyncSession,
    push: IntegrationPush,
) -> dict[str, tuple[str, str]]:
    """Map each of a push's ``task_ref``s to its human ``(T-NNN, title)``.

    The titles come from the push's **own** source Tasks :class:`StageVersion`
    (``source_stage_version_id``) — the exact version that produced these issues
    — so the ``compute_task_ref`` join is drift-proof: even if the workspace's
    current Tasks have since been renumbered/reworded, the refs here still match
    the version the issues were cut from. Returns an empty map when the source
    version is missing or empty (e.g. a legacy push), and omits any ref it can't
    resolve (an increment task not present in the baseline), so the caller falls
    back to the issue number for those. Read-only; never raises on bad content.
    """
    if push.source_stage_version_id is None:
        return {}
    version = await db.get(StageVersion, push.source_stage_version_id)
    if version is None or not version.content:
        return {}
    return {
        compute_task_ref(task.title): (task.ref, task.title)
        for task in parse_tasks(version.content)
    }


async def find_workspace_live_push(
    db: AsyncSession,
    workspace_id: UUID,
) -> IntegrationPush | None:
    """Return the workspace's live (non-``failed``) GitHub push, or ``None``.

    Used by the sync surface (T-273): a workspace syncs one repo (spec
    Assumption 8), but the ``(workspace_id, repo_id)`` index does not forbid a
    second live row, so this orders newest-first and takes the first rather than
    assuming exactly one.
    """
    result = await db.execute(
        select(IntegrationPush)
        .where(
            IntegrationPush.workspace_id == workspace_id,
            IntegrationPush.provider == "github",
            IntegrationPush.status != _NON_FAILED_STATUS,
        )
        .order_by(IntegrationPush.created_at.desc())
    )
    return result.scalars().first()

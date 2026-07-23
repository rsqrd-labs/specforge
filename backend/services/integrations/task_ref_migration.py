"""Lazy migration of legacy human (``T-NNN``) task refs to the stable identity.

GitHub integration audit #2: :class:`IntegrationPushTask` rows were historically
keyed on the *volatile* human ``T-NNN`` heading. That key shifts when the Tasks
stage is re-finalised with a renumber/reorder (``T-003`` → ``T-004`` …), which
corrupts the issue↔task mapping on the next resync/increment — each existing
issue is updated with the *next* task's content and the highest number opens a
duplicate. The load-bearing fix is to key every row on the content-derived
``task_parser.compute_task_ref(title)`` instead, which is invariant under
renumber (it hashes the normalised title, never the number).

This module migrates pre-existing rows onto that stable key **in place,
idempotently, before any matching runs**. The renumber-invariant source of truth
for a row's title is its live GitHub issue title (a renumber keeps the title;
Thought2Build issue titles are the bare task title — exactly ``compute_task_ref``'s
input). One bulk ``list_issues(state="all")`` recovers them; the call is skipped
entirely once no legacy-shaped refs remain, so steady-state resyncs never pay for
it.

The migration shares the same correctness boundary as the rest of #2: it cannot
un-corrupt GitHub state that a *prior* (pre-fix) buggy resync already mismapped —
it prevents the corruption going forward.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import IntegrationPushTask
from services.integrations.task_parser import compute_task_ref

logger = logging.getLogger(__name__)

# A legacy human ref is exactly ``T-`` followed by digits. The stable identity is
# ``task-<hex>`` (see ``compute_task_ref``), so this pattern never matches an
# already-migrated row — making the whole migration a safe, repeatable no-op once
# every row is stable.
_LEGACY_REF = re.compile(r"^T-\d+$")


def is_legacy_task_ref(task_ref: str | None) -> bool:
    """True for a volatile human ``T-NNN`` ref (i.e. not yet migrated)."""
    return bool(task_ref) and _LEGACY_REF.match(task_ref or "") is not None


async def migrate_legacy_task_refs(
    db: AsyncSession,
    push_id: UUID,
    client: Any,
    repo: str,
) -> int:
    """Repoint any legacy ``T-NNN`` task_ref on ``push_id`` to its stable identity.

    Returns the number of rows migrated. Fast path: returns ``0`` without any
    GitHub call when no legacy-shaped refs remain. Otherwise a single bulk
    ``list_issues(state="all")`` (closed *and* open — completed tasks must
    migrate too) recovers each issue's title, and rows are rewritten to
    ``compute_task_ref(title)`` under a collision guard that never violates the
    ``(push_id, task_ref)`` unique constraint.

    Best-effort per row: an issue whose title cannot be recovered (deleted, or
    missing from the list) is left on its legacy ref — harmless, because the
    webhook reconcile path matches by ``external_issue_number``, and a later sync
    retries the migration.
    """
    rows = list(
        (
            await db.execute(
                select(IntegrationPushTask).where(
                    IntegrationPushTask.push_id == push_id
                )
            )
        )
        .scalars()
        .all()
    )
    legacy = [row for row in rows if is_legacy_task_ref(row.task_ref)]
    if not legacy:
        return 0

    issues = await client.list_issues(repo, state="all")
    title_by_number: dict[int, str] = {}
    for issue in issues:
        if not isinstance(issue, dict) or "pull_request" in issue:
            # GitHub's issues endpoint also returns PRs — skip them.
            continue
        number = issue.get("number")
        title = issue.get("title")
        if isinstance(number, int) and isinstance(title, str):
            title_by_number[number] = title

    # Seed the collision guard with refs already stable so a legacy row can never
    # be repointed onto an in-use stable key (two same-titled tasks collide by
    # design; we keep the first and leave the rest legacy rather than crash).
    taken_refs = {row.task_ref for row in rows if not is_legacy_task_ref(row.task_ref)}
    migrated = 0
    for row in legacy:
        title = title_by_number.get(row.external_issue_number)
        if not title:
            continue
        stable = compute_task_ref(title)
        if stable in taken_refs:
            logger.warning(
                "task_ref_migration.collision push_id=%s issue=%s",
                str(push_id),
                row.external_issue_number,
            )
            continue
        row.task_ref = stable
        taken_refs.add(stable)
        migrated += 1

    if migrated:
        await db.commit()
        logger.info(
            "task_ref_migration.migrated push_id=%s count=%d",
            str(push_id),
            migrated,
        )
    return migrated

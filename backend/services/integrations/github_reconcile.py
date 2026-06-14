"""Bidirectional sync reconcile job (Phase 21 — T-272).

Runs on the worker as ``reconcile_event(delivery_id, event_type, raw)`` — the
single delivery dispatcher the webhook enqueues (T-271). It re-parses the stored
raw payload and routes by ``(event_type, action)``; closing a task's issue (or
merging the PR that closes it) flips that task to ``done`` in SpecForge, so the
workspace becomes a live dashboard.

Security (confused-deputy, spec §12): payload identity is never trusted to widen
scope. A delivery for ``repository.id`` may only mutate pushes whose recorded
:class:`GitHubInstallation` matches the delivery's own ``installation.id`` — see
:func:`services.integrations.push_repo.find_live_pushes_for_event`. Resolution is
on the immutable numeric ``repo_id``, never the mutable ``repo_full_name``.

Out-of-order safety: a task carries ``synced_at`` as the high-water mark of the
*event timestamp* that last changed its state. A transition is applied only when
the incoming event's timestamp is not older than ``synced_at``, so a late
``reopened`` cannot regress a task a newer ``closed`` already completed.

INVARIANT — ``synced_at`` MUST only ever hold an *event* timestamp, never
``now()``. ``done_at`` is the wall-clock record; ``synced_at`` is the gate. If
any reconcile/backfill path sets ``synced_at = now()``, every subsequent
real-time event would be ``< now()`` and silently dropped forever (T-273 backfill
must respect this).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    GitHubInstallation,
    GitHubWebhookEvent,
    IncrementIdea,
    IntegrationPush,
    IntegrationPushTask,
    Stage,
    StageVersion,
)
from services.integrations import github_install_service
from services.integrations.github_api_client import (
    make_app_github_client,
    make_shared_async_client,
)
from services.integrations.github_app_auth import make_token_provider
from services.integrations.push_repo import find_live_pushes_for_event
from services.observability import GITHUB_RECONCILE_LAG_SECONDS
from services.security.sanitizer import sanitize_text

GITHUB_PROVIDER = "github"

logger = structlog.get_logger(__name__)

# GitHub closing keywords that auto-close an issue when a PR merges. Parsing
# these from the PR body is the documented issue↔PR linkage (NOT branch-name
# inference, which the spec forbids).
_CLOSING_KEYWORDS_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b",
    re.IGNORECASE,
)

_ISSUE_ACTIONS = {"closed", "reopened", "edited"}
_PR_CHECK_ACTIONS = {"opened", "synchronize", "reopened"}
_LIFECYCLE_ACTIONS = {"suspend", "unsuspend", "deleted"}

# Issue events that may surface a backlog idea, and the labels that mark one
# (T-280). A GitHub issue tagged ``idea``/``enhancement`` flows back into the
# workspace's idea backlog as ``source='github'``.
_IDEA_ACTIONS = {"opened", "reopened", "labeled", "edited"}
_IDEA_LABELS = {"idea", "enhancement"}


async def reconcile_event(
    ctx: dict[str, Any],
    delivery_id: str,
    event_type: str,
    raw: bytes | str,
    *,
    db: AsyncSession | None = None,
    enqueue_fn: Any = None,
) -> None:
    """Worker entrypoint: dispatch one verified webhook delivery.

    Idempotent + at-least-once safe (the delivery was already deduped by the
    ``github_webhook_events`` row; re-running is a no-op). ``db`` / ``enqueue_fn``
    are injectable for tests; production opens a session and uses the real queue.
    """
    if db is not None:
        await _dispatch(db, delivery_id, event_type, raw, enqueue_fn)
        return
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await _dispatch(session, delivery_id, event_type, raw, enqueue_fn)


async def _dispatch(
    db: AsyncSession,
    delivery_id: str,
    event_type: str,
    raw: bytes | str,
    enqueue_fn: Any,
) -> None:
    payload = json.loads(raw)
    action = payload.get("action")

    if event_type == "issues":
        if action in _ISSUE_ACTIONS:
            await _reconcile_issue(db, payload, action)
        if action in _IDEA_ACTIONS:
            await _capture_idea(db, payload)
    elif event_type == "pull_request":
        if action == "closed" and (payload.get("pull_request") or {}).get("merged"):
            await _reconcile_merged_pr(db, payload)
        if action in _PR_CHECK_ACTIONS:
            await _route_pr_check(db, payload, enqueue_fn)
    elif event_type == "check_suite":
        await _route_pr_check(db, payload, enqueue_fn)
    elif event_type == "projects_v2_item":
        await _route_projects_sync(db, payload, enqueue_fn)
    elif event_type == "installation":
        await _route_installation(db, payload, action)
    elif event_type == "installation_repositories":
        await _route_installation_repositories(db, payload, action)
    # Any other event type is acknowledged and ignored.

    await _mark_processed(db, delivery_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Issue / PR reconciliation
# ---------------------------------------------------------------------------


async def _reconcile_issue(
    db: AsyncSession, payload: dict[str, Any], action: str
) -> None:
    """Apply an ``issues`` event. A plain close is attributed ``manual``; a
    merged PR that closed the issue upgrades it to ``pr_merge`` via the
    ``pull_request`` event."""
    repo_id, installation_id = _identity(payload)
    if repo_id is None or installation_id is None:
        return
    issue = payload.get("issue") or {}
    issue_number = issue.get("number")
    if not isinstance(issue_number, int):
        return
    event_ts = _parse_ts(issue.get("updated_at"))
    if event_ts is None:
        return

    if action == "edited":
        # A title/body edit is not a state transition. It must NOT advance the
        # out-of-order high-water mark (synced_at) — doing so could make a
        # later-arriving but earlier-timestamped 'closed' look stale and be
        # dropped. SpecForge does not sync issue titles back, so ignore it.
        return

    for task in await _matched_tasks(db, repo_id, installation_id, issue_number):
        if action == "reopened":
            _apply_reopen(task, event_ts=event_ts)
        elif action == "closed":
            changed = _apply_done(task, done_via="manual", event_ts=event_ts)
            if changed:
                _audit_done(task, payload, done_via="manual")


async def _reconcile_merged_pr(db: AsyncSession, payload: dict[str, Any]) -> None:
    """A merged PR closes the issues it references with closing keywords; those
    tasks are completed with ``done_via='pr_merge'`` (authoritative)."""
    repo_id, installation_id = _identity(payload)
    if repo_id is None or installation_id is None:
        return
    pr = payload.get("pull_request") or {}
    event_ts = _parse_ts(pr.get("merged_at") or pr.get("updated_at"))
    if event_ts is None:
        return
    closed_numbers = _closing_issue_numbers(pr.get("body") or "")
    if not closed_numbers:
        return
    for issue_number in closed_numbers:
        for task in await _matched_tasks(db, repo_id, installation_id, issue_number):
            changed = _apply_done(task, done_via="pr_merge", event_ts=event_ts)
            if changed:
                _audit_done(task, payload, done_via="pr_merge")


async def _capture_idea(db: AsyncSession, payload: dict[str, Any]) -> None:
    """Flow a GitHub ``idea``/``enhancement`` issue into the workspace backlog.

    Confused-deputy scoped: the idea is attached only to workspaces whose live
    push matches the delivery's ``(repo_id, installation_id)`` — an issue from
    one installation can never seed another's backlog. Idempotent at-least-once:
    deduped on ``(workspace_id, external_ref)`` so re-seeing the same issue
    (``labeled`` then ``edited`` then a redelivery) inserts at most one row.
    """
    repo_id, installation_id = _identity(payload)
    if repo_id is None or installation_id is None:
        return
    issue = payload.get("issue") or {}
    number = issue.get("number")
    if not isinstance(number, int) or not _has_idea_label(issue):
        return

    pushes = await find_live_pushes_for_event(db, repo_id, installation_id)
    if not pushes:
        return  # not ours / wrong installation → ignore

    external_ref = f"gh-issue:{number}"
    raw_title = issue.get("title")
    text = (
        sanitize_text(str(raw_title)).strip() if isinstance(raw_title, str) else ""
    ) or f"GitHub issue #{number}"

    seen: set[Any] = set()
    for push in pushes:
        workspace_id = push.workspace_id
        if workspace_id in seen:
            continue
        seen.add(workspace_id)
        already = (
            await db.execute(
                select(IncrementIdea).where(
                    IncrementIdea.workspace_id == workspace_id,
                    IncrementIdea.external_ref == external_ref,
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            continue
        db.add(
            IncrementIdea(
                workspace_id=workspace_id,
                source="github",
                external_ref=external_ref,
                text=text,
                status="open",
            )
        )
        logger.info(
            "github.reconcile.idea_captured",
            workspace_id=str(workspace_id),
            external_ref=external_ref,
            repo_id=repo_id,
            installation_id=installation_id,
        )


def _has_idea_label(issue: dict[str, Any]) -> bool:
    """True if the issue carries an ``idea`` or ``enhancement`` label."""
    for label in issue.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.lower() in _IDEA_LABELS:
            return True
    return False


async def _matched_tasks(
    db: AsyncSession,
    repo_id: int,
    installation_id: int,
    issue_number: int,
) -> list[IntegrationPushTask]:
    """The task rows a delivery may mutate, confused-deputy scoped.

    Resolves the live pushes for ``(repo_id, installation_id)`` — never by
    ``repo_full_name`` — then the matching ``external_issue_number`` task in each
    (two workspaces may track the same repo; apply to all that match).
    """
    pushes = await find_live_pushes_for_event(db, repo_id, installation_id)
    if not pushes:
        return []  # not ours / wrong installation → ignore
    result = await db.execute(
        select(IntegrationPushTask).where(
            IntegrationPushTask.push_id.in_([p.id for p in pushes]),
            IntegrationPushTask.external_issue_number == issue_number,
        )
    )
    return list(result.scalars())


def _apply_done(
    task: IntegrationPushTask,
    *,
    done_via: str,
    event_ts: datetime,
) -> bool:
    """Complete a task. Out-of-order gated on ``synced_at``; allows a
    ``manual`` → ``pr_merge`` upgrade but never a downgrade. Returns True only on
    a fresh open→done transition (for the audit row)."""
    if task.synced_at is not None and event_ts < task.synced_at:
        return False
    task.synced_at = event_ts
    if task.state != "done":
        task.state = "done"
        task.done_at = datetime.now(UTC)
        task.done_via = done_via
        return True
    if done_via == "pr_merge" and task.done_via != "pr_merge":
        task.done_via = "pr_merge"  # upgrade attribution; not a new completion
    return False


def _apply_reopen(task: IntegrationPushTask, *, event_ts: datetime) -> bool:
    """Reopen a task iff the event is not older than the last applied event
    (out-of-order guard: a stale ``reopened`` cannot regress a newer close)."""
    if task.synced_at is not None and event_ts < task.synced_at:
        return False
    task.synced_at = event_ts
    if task.state == "done":
        task.state = "open"
        task.done_at = None
        task.done_via = None
        return True
    return False


# ---------------------------------------------------------------------------
# Fan-out routing (forward-coupled jobs: T-281/T-282)
# ---------------------------------------------------------------------------


async def _route_pr_check(
    db: AsyncSession, payload: dict[str, Any], enqueue_fn: Any
) -> None:
    """pull_request(opened|synchronize|reopened) and check_suite → ``pr_check``
    (T-282), one job per matched push.

    A ``check_suite:rerequested`` event is an explicit user re-run, so it is
    tagged ``manual``; every other routed event is an automatic push tagged
    ``auto``. The pr_check worker uses that to honour the installation's
    ``manual`` pr_check_mode (issue #27 Phase 4)."""
    repo_id, installation_id = _identity(payload)
    if repo_id is None or installation_id is None:
        return
    pr_number = _pr_number(payload)
    if pr_number is None:
        return
    trigger = "manual" if payload.get("action") == "rerequested" else "auto"
    pushes = await find_live_pushes_for_event(db, repo_id, installation_id)
    for push in pushes:
        await _enqueue(enqueue_fn, "pr_check", str(push.id), pr_number, trigger)


async def _route_projects_sync(
    db: AsyncSession, payload: dict[str, Any], enqueue_fn: Any
) -> None:
    """projects_v2_item → ``projects_sync`` (T-281) for each matched push, when
    the payload carries a resolvable repository."""
    repo_id, installation_id = _identity(payload)
    if repo_id is None or installation_id is None:
        return
    pushes = await find_live_pushes_for_event(db, repo_id, installation_id)
    for push in pushes:
        await _enqueue(enqueue_fn, "projects_sync", str(push.id))


async def _route_installation(
    db: AsyncSession, payload: dict[str, Any], action: str | None
) -> None:
    """installation suspend/unsuspend/deleted → the T-270 lifecycle handler."""
    if action not in _LIFECYCLE_ACTIONS:
        return
    installation_id = (payload.get("installation") or {}).get("id")
    if isinstance(installation_id, int):
        await github_install_service.apply_installation_event(
            db, action=action, installation_id=installation_id
        )


async def _route_installation_repositories(
    db: AsyncSession, payload: dict[str, Any], action: str | None
) -> None:
    """installation_repositories added/removed → the T-270 lifecycle handler."""
    installation_id = (payload.get("installation") or {}).get("id")
    if not isinstance(installation_id, int):
        return
    removed = [
        r.get("id")
        for r in (payload.get("repositories_removed") or [])
        if isinstance(r.get("id"), int)
    ]
    await github_install_service.apply_installation_repositories_event(
        db,
        action=action or "",
        installation_id=installation_id,
        removed_repo_ids=removed,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _identity(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    """Return ``(repo_id, installation_id)`` from the payload, or Nones.

    The installation id is the confused-deputy key — absent ⇒ we cannot attribute
    the event safely, so the caller ignores it.
    """
    repo = payload.get("repository") or {}
    installation = payload.get("installation") or {}
    repo_id = repo.get("id")
    installation_id = installation.get("id")
    return (
        repo_id if isinstance(repo_id, int) else None,
        installation_id if isinstance(installation_id, int) else None,
    )


def _pr_number(payload: dict[str, Any]) -> int | None:
    pr = payload.get("pull_request")
    if isinstance(pr, dict) and isinstance(pr.get("number"), int):
        return pr["number"]
    # check_suite carries its associated PRs.
    suite = payload.get("check_suite") or {}
    prs = suite.get("pull_requests") or []
    for entry in prs:
        if isinstance(entry, dict) and isinstance(entry.get("number"), int):
            return entry["number"]
    return None


def _closing_issue_numbers(body: str) -> list[int]:
    """Issue numbers a PR body closes via GitHub closing keywords."""
    return [int(m) for m in _CLOSING_KEYWORDS_RE.findall(body)]


def _parse_ts(value: Any) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp into a tz-aware UTC datetime, or None.

    Always tz-aware so comparisons against the DB's tz-aware ``synced_at`` never
    raise (the bug class fixed in T-267's ``_parse_github_timestamp``).
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _enqueue(enqueue_fn: Any, job: str, *args: Any) -> None:
    if enqueue_fn is None:
        from services.queue import enqueue as _real_enqueue

        await _real_enqueue(job, *args)
    else:
        await enqueue_fn(job, *args)


async def _mark_processed(db: AsyncSession, delivery_id: str) -> None:
    """Stamp ``processed_at`` on the delivery row and record reconcile lag."""
    result = await db.execute(
        select(GitHubWebhookEvent).where(GitHubWebhookEvent.delivery_id == delivery_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return
    now = datetime.now(UTC)
    row.processed_at = now
    received = row.received_at
    if received is not None:
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        GITHUB_RECONCILE_LAG_SECONDS.observe(max(0.0, (now - received).total_seconds()))


def _audit_done(
    task: IntegrationPushTask, payload: dict[str, Any], *, done_via: str
) -> None:
    """Structured audit of a task completion — identifiers only, never the
    raw payload (spec §24.10)."""
    repo = payload.get("repository") or {}
    installation = payload.get("installation") or {}
    logger.info(
        "github.reconcile.task_done",
        push_id=str(task.push_id),
        task_ref=task.task_ref,
        issue_number=task.external_issue_number,
        repo_id=repo.get("id"),
        installation_id=installation.get("id"),
        done_via=done_via,
    )


# ---------------------------------------------------------------------------
# Backfill — recover events missed while the worker was down (T-273)
# ---------------------------------------------------------------------------


# A push stuck in 'pending' whose arq job no longer exists is treated as a
# crashed export and failed, so the partial unique index (status <> 'failed')
# stops blocking re-export of that repo. We key on arq job ABSENCE rather than a
# created_at age threshold: integration_pushes has no per-attempt timestamp
# (created_at is the first export's time and the row is reused), so a time
# threshold would false-positive a healthy re-export. The arq job_timeout
# (T-269) backstops a genuinely hung job.


async def backfill_repo(
    ctx: dict[str, Any],
    push_id: str,
    *,
    db: AsyncSession | None = None,
    client: Any = None,
) -> None:
    """Reconcile a push's task states from GitHub's issues list (T-273).

    Recovers closures/reopens missed while the worker was down. Idempotent with
    the webhook reconcile path: it reuses the same out-of-order-gated
    transitions, so re-seeing a state is a no-op and a webhook-set ``pr_merge``
    is never downgraded to ``manual``.
    """
    if db is not None:
        await _run_backfill(db, push_id, client)
        return
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await _run_backfill(session, push_id, client)


async def _run_backfill(db: AsyncSession, push_id: str, client: Any) -> None:
    push = (
        await db.execute(select(IntegrationPush).where(IntegrationPush.id == push_id))
    ).scalar_one_or_none()
    if push is None or push.repo_full_name is None or push.repo_id is None:
        return
    installation = (
        await db.execute(
            select(GitHubInstallation).where(
                GitHubInstallation.id == push.installation_id
            )
        )
    ).scalar_one_or_none()
    if installation is None:
        return

    tasks = list(
        (
            await db.execute(
                select(IntegrationPushTask).where(
                    IntegrationPushTask.push_id == push.id
                )
            )
        ).scalars()
    )
    if not tasks:
        return
    by_number = {t.external_issue_number: t for t in tasks}
    since = _last_synced_iso(tasks)

    if client is not None:
        issues = await client.list_issues(push.repo_full_name, state="all", since=since)
    else:
        async with make_shared_async_client() as http:
            from database import get_shared_redis

            provider = make_token_provider(get_shared_redis(), http)
            built = make_app_github_client(provider, installation.installation_id, http)
            issues = await built.list_issues(
                push.repo_full_name, state="all", since=since
            )

    changed = False
    for issue in issues:
        # GitHub's issues endpoint also returns PRs — they carry a
        # 'pull_request' key. Filtering them out is mandatory (a PR is not a task
        # issue).
        if "pull_request" in issue:
            continue
        number = issue.get("number")
        task = by_number.get(number) if isinstance(number, int) else None
        if task is None:
            continue
        event_ts = _parse_ts(issue.get("updated_at"))
        if event_ts is None:
            continue
        if issue.get("state") == "closed":
            if _apply_done(task, done_via="manual", event_ts=event_ts):
                changed = True
        elif issue.get("state") == "open":
            if _apply_reopen(task, event_ts=event_ts):
                changed = True
    if changed:
        await db.commit()


def _last_synced_iso(tasks: list[IntegrationPushTask]) -> str | None:
    """The most recent ``synced_at`` across a push's tasks, as an ISO string —
    the ``since`` cursor so backfill only pulls rows updated after the last
    reconcile. ``None`` (no prior sync) pulls the full history."""
    stamps = [t.synced_at for t in tasks if t.synced_at is not None]
    if not stamps:
        return None
    latest = max(stamps)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    return latest.astimezone(UTC).isoformat()


# ---------------------------------------------------------------------------
# Periodic drift reconciliation (cron) — stuck-pending sweep + backfill
# ---------------------------------------------------------------------------


async def reconcile_drift(
    ctx: dict[str, Any],
    *,
    db: AsyncSession | None = None,
    enqueue_fn: Any = None,
    is_job_alive: Any = None,
) -> None:
    """Periodic cron (T-273): sweep crashed 'pending' pushes and re-backfill.

    1. Stuck-pending sweep (release-blocking): a push 'pending' whose arq job is
       gone is a crashed export; mark it 'failed' so the repo is not permanently
       locked out of re-export by the live partial index.
    2. Catch missed events: enqueue ``backfill_repo`` for each completed push.
    """
    if is_job_alive is None:
        is_job_alive = _arq_job_alive_checker((ctx or {}).get("redis"))
    if db is not None:
        await _run_reconcile_drift(db, enqueue_fn, is_job_alive)
        return
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await _run_reconcile_drift(session, enqueue_fn, is_job_alive)


async def _run_reconcile_drift(
    db: AsyncSession, enqueue_fn: Any, is_job_alive: Any
) -> int:
    pending = list(
        (
            await db.execute(
                select(IntegrationPush).where(IntegrationPush.status == "pending")
            )
        ).scalars()
    )
    swept = 0
    for push in pending:
        if not await is_job_alive(str(push.id)):
            push.status = "failed"  # unblock re-export of this repo
            swept += 1
            logger.warning(
                "github.reconcile.stuck_pending_failed", push_id=str(push.id)
            )
    if swept:
        await db.commit()

    completed = list(
        (
            await db.execute(
                select(IntegrationPush).where(IntegrationPush.status == "completed")
            )
        ).scalars()
    )
    for push in completed:
        await _enqueue(enqueue_fn, "backfill_repo", str(push.id))
    return swept


def _arq_job_alive_checker(redis: Any) -> Any:
    """Return an ``async (push_id) -> bool`` that reports whether the push's arq
    job still exists. The push_id is the job_id (T-269). Conservative when the
    queue is unreachable: report alive so a real export is never falsely swept."""

    async def _alive(push_id: str) -> bool:
        if redis is None:
            return True
        from arq.jobs import Job, JobStatus

        status = await Job(job_id=push_id, redis=redis).status()
        return status != JobStatus.not_found

    return _alive


# ---------------------------------------------------------------------------
# Drift detection on Tasks re-finalise (called from StageManager.finalise)
# ---------------------------------------------------------------------------


async def mark_pushes_stale_on_tasks_drift(db: AsyncSession, workspace_id: Any) -> None:
    """Mark a workspace's live GitHub pushes ``stale`` when Tasks has drifted.

    Called inside ``StageManager.finalise`` (same transaction) when the Tasks
    stage is re-finalised: any non-``failed`` push whose
    ``source_stage_version_id`` differs from the workspace's current finalised
    Tasks ``StageVersion`` is now out of sync. The caller commits.
    """
    current_version_id = await _current_tasks_version_id(db, workspace_id)
    if current_version_id is None:
        return
    pushes = list(
        (
            await db.execute(
                select(IntegrationPush).where(
                    IntegrationPush.workspace_id == workspace_id,
                    IntegrationPush.provider == GITHUB_PROVIDER,
                    IntegrationPush.status != "failed",
                )
            )
        ).scalars()
    )
    for push in pushes:
        if (
            push.source_stage_version_id is not None
            and push.source_stage_version_id != current_version_id
        ):
            push.status = "stale"


async def _current_tasks_version_id(db: AsyncSession, workspace_id: Any) -> Any:
    stage = (
        await db.execute(
            select(Stage).where(
                Stage.workspace_id == workspace_id, Stage.type == "tasks"
            )
        )
    ).scalar_one_or_none()
    if stage is None:
        return None
    return (
        await db.execute(
            select(StageVersion.id).where(
                StageVersion.stage_id == stage.id,
                StageVersion.version == stage.current_version,
            )
        )
    ).scalar_one_or_none()

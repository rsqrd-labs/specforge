import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"

import { BrandLogo } from "../components/shared/BrandLogo"
import { ExportStatusBadge } from "../components/github/ExportStatusBadge"
import {
  BranchIcon,
  DriftIcon,
  GitHubIcon,
  IdeaIcon,
  PullRequestIcon,
  ShippedCheckIcon,
} from "../components/shared/icons"
import {
  getGitHubPush,
  getWorkspace,
  listIncrements,
  type IntegrationPushRead,
} from "../services/api"
import { useGitHubSync } from "../hooks/useGitHubSync"
import type {
  Increment,
  PushStatus,
  TaskSyncState,
  TaskVersionSyncStatus,
} from "../types/github"

export function taskSyncPresentation(
  status: PushStatus,
  taskSyncStatus: TaskVersionSyncStatus,
  syncPaused: boolean,
): { value: string; detail: string } {
  if (syncPaused) {
    return { value: "Sync paused", detail: "Reconnect GitHub to resume" }
  }
  if (status === "pending") {
    return { value: "Updating", detail: "Pushing task changes" }
  }
  if (taskSyncStatus === "changes_pending") {
    return {
      value: "Changes pending",
      detail: "Tasks changed after the last push",
    }
  }
  if (taskSyncStatus === "up_to_date") {
    return {
      value: "Up to date",
      detail: "Current Tasks version is on GitHub",
    }
  }
  return { value: "Not verified", detail: "Push Tasks to establish sync" }
}

function issueHref(
  repoUrl: string | null,
  repoFullName: string | null,
  issueNumber: number,
): string | null {
  const base = repoUrl?.replace(/\/+$/, "")
  if (base) return `${base}/issues/${issueNumber}`
  if (repoFullName) return `https://github.com/${repoFullName}/issues/${issueNumber}`
  return null
}

function formatWhen(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const diffMs = Date.now() - then
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(then)
}

const INCREMENT_STATUS_LABEL: Record<Increment["status"], string> = {
  draft: "Draft",
  generating: "Generating",
  ready: "Ready",
  pushed: "Shipped",
  stale: "Needs sync",
}

function TaskRow({
  task,
  repoUrl,
  repoFullName,
  flash,
}: {
  task: TaskSyncState
  repoUrl: string | null
  repoFullName: string | null
  flash: boolean
}) {
  const isDone = task.state === "done"
  const viaPr = task.done_via === "pr_merge"
  const href = issueHref(repoUrl, repoFullName, task.issue_number)
  const when = formatWhen(task.done_at ?? task.synced_at)
  // Human identity from the source Tasks version; fall back to the issue number
  // when the title can't be resolved. The opaque task_ref hash is never shown.
  const heading = task.title ?? `Issue #${task.issue_number}`

  return (
    <li
      className={[
        "ghx-task",
        isDone ? "done" : "open",
        flash ? "just-shipped" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span
        className={`ghx-task-check${isDone ? " done" : ""}${viaPr ? " via-pr" : ""}`}
        aria-hidden="true"
      >
        <ShippedCheckIcon />
      </span>
      <div className="ghx-task-main">
        <span className="ghx-task-heading">
          {task.human_ref && (
            <span className="ghx-task-ref">{task.human_ref}</span>
          )}
          <span className="ghx-task-title" title={heading}>
            {heading}
          </span>
        </span>
        <span className="ghx-task-state">
          {isDone ? (viaPr ? "Shipped · via PR" : "Shipped") : "Open"}
          {when && <span className="ghx-task-when"> · {when}</span>}
        </span>
      </div>
      {href && (
        <a
          className="ghx-task-link"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
        >
          Issue #{task.issue_number} ↗
        </a>
      )}
    </li>
  )
}

export default function WorkspaceGitHub() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const sync = useGitHubSync(id, Boolean(id))
  const [push, setPush] = useState<IntegrationPushRead | null>(null)
  const [increments, setIncrements] = useState<Increment[]>([])
  const [workspaceName, setWorkspaceName] = useState<string | null>(null)
  const [metaLoaded, setMetaLoaded] = useState(false)
  const [actionNote, setActionNote] = useState<string | null>(null)

  const loadMeta = useCallback(async () => {
    if (!id) return
    const [p, inc, ws] = await Promise.all([
      getGitHubPush(id).catch(() => null),
      listIncrements(id).catch(() => [] as Increment[]),
      getWorkspace(id).catch(() => null),
    ])
    setPush(p)
    setIncrements(inc)
    setWorkspaceName(ws?.name ?? null)
    setMetaLoaded(true)
  }, [id])

  useEffect(() => {
    void loadMeta()
  }, [loadMeta])

  // One-time highlight of task rows that flip open→done between polls.
  const previouslyDone = useRef<Set<string> | null>(null)
  const [justShipped, setJustShipped] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (!sync.data) return
    const current = new Set(
      sync.data.tasks.filter((t) => t.state === "done").map((t) => t.task_ref),
    )
    const previous = previouslyDone.current
    previouslyDone.current = current
    if (previous === null) return
    const newly = [...current].filter((ref) => !previous.has(ref))
    if (newly.length === 0) return
    setJustShipped(new Set(newly))
    const handle = window.setTimeout(() => setJustShipped(new Set()), 1400)
    return () => window.clearTimeout(handle)
  }, [sync.data])

  const data = sync.data
  const repoFullName = sync.repoFullName ?? push?.repo_full_name ?? null
  const repoUrl = sync.repoUrl ?? push?.repo_url ?? null
  const loading = (sync.loading && !data) || !metaLoaded
  const hasExport = Boolean(data || push)

  const total = data?.total ?? push?.issue_count ?? 0
  const shipped = data?.shipped ?? 0
  const open = Math.max(total - shipped, 0)
  const pct = total > 0 ? Math.round((shipped / total) * 100) : 0
  const status: PushStatus =
    data?.status ?? (push?.status as PushStatus | undefined) ?? "pending"
  const taskSyncStatus = data?.task_sync_status ?? "unknown"
  const syncPaused =
    (data?.sync_paused ?? false) || sync.connection !== "connected"
  const outOfSync = taskSyncStatus === "changes_pending"
  const pushedWhen = formatWhen(push?.pushed_at ?? null)

  const taskSyncCopy = taskSyncPresentation(
    status,
    taskSyncStatus,
    syncPaused,
  )

  const handleResync = useCallback(async () => {
    setActionNote(null)
    try {
      await sync.resync()
      setActionNote("Re-sync started — issues will update here shortly.")
    } catch {
      setActionNote("Could not start the re-sync. Please try again.")
    }
    void loadMeta()
  }, [sync, loadMeta])

  const handleBackfill = useCallback(async () => {
    setActionNote(null)
    try {
      const completed = await sync.refreshFromGitHub()
      setActionNote(
        completed
          ? "GitHub is up to date."
          : "GitHub is taking longer than expected. Please try again.",
      )
    } catch {
      setActionNote("GitHub is taking longer than expected. Please try again.")
    }
    void loadMeta()
  }, [sync, loadMeta])

  const title = repoFullName ?? workspaceName ?? "GitHub export"

  return (
    <div className="ghx-page">
      <div className="ambient-field" aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
        <div className="ambient-band band-slate" />
      </div>

      <nav className="ghx-nav">
        <div className="ghx-nav-inner">
          <button
            type="button"
            className="ghx-nav-back"
            onClick={() => navigate(id ? `/workspace/${id}` : "/dashboard")}
            aria-label="Back to workspace"
          >
            <span aria-hidden="true">←</span>
            Workspace
          </button>
          <div className="ghx-nav-brand">
            <BrandLogo size="small" decorative />
            <span className="ghx-nav-divider">/</span>
            <Link to="/github" className="ghx-nav-section-link">
              Exports
            </Link>
          </div>
          <span className="ghx-nav-spacer" aria-hidden="true" />
        </div>
      </nav>

      <main className="ghx-main">
        {loading ? (
          <div className="ghx-skeleton" aria-busy="true">
            <span className="ghx-skeleton-title" />
            <div className="ghx-skeleton-tiles">
              <span />
              <span />
              <span />
              <span />
            </div>
            <span className="ghx-skeleton-bar" />
          </div>
        ) : !hasExport ? (
          <div className="ghx-empty">
            <span className="ghx-empty-mark" aria-hidden="true">
              <GitHubIcon />
            </span>
            <h1 className="ghx-empty-title">Not exported yet</h1>
            <p className="ghx-empty-body">
              {workspaceName ? <strong>{workspaceName}</strong> : "This workspace"}{" "}
              hasn&apos;t been pushed to GitHub. Finalise the Tasks stage, then
              export to create one issue per task and track them here.
            </p>
            <button
              type="button"
              className="ghx-btn ghx-btn-primary"
              onClick={() => navigate(id ? `/workspace/${id}` : "/dashboard")}
            >
              Open workspace
            </button>
          </div>
        ) : (
          <>
            {/* Hero */}
            <header className="ghx-hero">
              <div className="ghx-hero-copy">
                <div className="ghx-breadcrumb">
                  <Link to="/dashboard">Dashboard</Link>
                  <span aria-hidden="true">/</span>
                  <Link to="/github">Exports</Link>
                  {workspaceName && (
                    <>
                      <span aria-hidden="true">/</span>
                      <span className="ghx-breadcrumb-current">{workspaceName}</span>
                    </>
                  )}
                </div>
                <h1 className="ghx-hero-title">
                  <span className="ghx-hero-mark" aria-hidden="true">
                    <GitHubIcon />
                  </span>
                  {title}
                </h1>
                <div className="ghx-hero-meta">
                  <ExportStatusBadge
                    status={status}
                    outOfSync={outOfSync}
                    syncPaused={syncPaused}
                    taskSyncStatus={taskSyncStatus}
                  />
                  {pushedWhen && (
                    <span className="ghx-hero-pushed">Last pushed {pushedWhen}</span>
                  )}
                </div>
              </div>
              {repoUrl && (
                <a
                  className="ghx-btn ghx-btn-primary ghx-hero-open"
                  href={repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open on GitHub ↗
                </a>
              )}
            </header>

            {sync.connection !== "connected" && (
              <div className="ghx-notice ghx-notice-paused" role="status">
                <span className="ghx-notice-icon" aria-hidden="true">
                  <GitHubIcon />
                </span>
                <span>
                  Sync paused — the GitHub App looks disconnected or suspended.
                </span>
                <Link to="/settings" className="ghx-notice-action">
                  Reconnect
                </Link>
              </div>
            )}

            {/* Metric tiles */}
            <section className="ghx-tiles" aria-label="Export summary">
              <div className="ghx-tile">
                <span className="ghx-tile-label">Issues created</span>
                <span className="ghx-tile-value">{total}</span>
                <span className="ghx-tile-sub">one per task</span>
              </div>
              <div className="ghx-tile ghx-tile-accent">
                <span className="ghx-tile-label">Shipped</span>
                <span className="ghx-tile-value">
                  {shipped}
                  <span className="ghx-tile-of">/ {total}</span>
                </span>
                <span className="ghx-tile-sub">{pct}% complete</span>
              </div>
              <div className="ghx-tile">
                <span className="ghx-tile-label">Open</span>
                <span className="ghx-tile-value">{open}</span>
                <span className="ghx-tile-sub">still on GitHub</span>
              </div>
              <div
                className={`ghx-tile${outOfSync || syncPaused ? " ghx-tile-warn" : ""}`}
              >
                <span className="ghx-tile-label">Task sync</span>
                <span className="ghx-tile-value ghx-tile-value-sm">
                  {taskSyncCopy.value}
                </span>
                <span className="ghx-tile-sub">{taskSyncCopy.detail}</span>
              </div>
            </section>

            {/* Progress */}
            <section className="ghx-progress-block" aria-label="Completion">
              <div
                className={`ghx-progress${pct === 100 ? " complete" : ""}`}
                role="progressbar"
                aria-valuenow={shipped}
                aria-valuemin={0}
                aria-valuemax={total}
                aria-label={`${shipped} of ${total} tasks shipped`}
              >
                <span className="ghx-progress-fill" style={{ width: `${pct}%` }} />
              </div>
              <p className="ghx-progress-caption">
                {total === 0
                  ? "No tasks to ship yet."
                  : pct === 100
                    ? "Every task has shipped. 🎉"
                    : `${shipped} of ${total} tasks shipped — ${open} to go.`}
              </p>
            </section>

            {/* Actions */}
            <section className="ghx-actions" aria-label="Sync actions">
              <div className="ghx-action">
                <div className="ghx-action-copy">
                  <span className="ghx-action-title">
                    {outOfSync ? "Push changed tasks" : "Push tasks to GitHub"}
                  </span>
                  <span className="ghx-action-sub">
                    Push the current Tasks to GitHub — update changed issues and
                    open issues for any new tasks.
                  </span>
                </div>
                <button
                  type="button"
                  className={`ghx-btn ${outOfSync ? "ghx-btn-primary" : "ghx-btn-ghost"}`}
                  onClick={() => void handleResync()}
                  disabled={sync.resyncing || sync.connection !== "connected"}
                >
                  {sync.resyncing ? "Pushing…" : "Push task changes"}
                </button>
              </div>
              <div className="ghx-action">
                <div className="ghx-action-copy">
                  <span className="ghx-action-title">Check GitHub</span>
                  <span className="ghx-action-sub">
                    Pull the latest issue states and update task completion here.
                  </span>
                </div>
                <button
                  type="button"
                  className="ghx-btn ghx-btn-ghost"
                  onClick={() => void handleBackfill()}
                  disabled={sync.refreshing || sync.connection !== "connected"}
                >
                  {sync.refreshing ? "Checking…" : "Check now"}
                </button>
              </div>
              {actionNote && (
                <p className="ghx-action-note" role="status">
                  {actionNote}
                </p>
              )}
            </section>

            {/* Task → issue list */}
            <section className="ghx-section" aria-label="Tasks and issues">
              <div className="ghx-section-head">
                <h2 className="ghx-section-title">Tasks &amp; issues</h2>
                <span className="ghx-section-count">
                  {shipped} of {total} closed
                </span>
              </div>
              {data && data.tasks.length > 0 ? (
                <ul className="ghx-task-list">
                  {data.tasks.map((task) => (
                    <TaskRow
                      key={task.task_ref}
                      task={task}
                      repoUrl={repoUrl}
                      repoFullName={repoFullName}
                      flash={justShipped.has(task.task_ref)}
                    />
                  ))}
                </ul>
              ) : (
                <p className="ghx-section-empty">
                  No task issues are tracked for this export yet.
                </p>
              )}
            </section>

            {/* Increment timeline */}
            {increments.length > 0 && (
              <section className="ghx-section" aria-label="Increment timeline">
                <div className="ghx-section-head">
                  <h2 className="ghx-section-title">Increment timeline</h2>
                  <span className="ghx-section-count">
                    {increments.length}{" "}
                    {increments.length === 1 ? "entry" : "entries"}
                  </span>
                </div>
                <ol className="ghx-timeline">
                  {increments.map((inc) => (
                    <li key={inc.id} className="ghx-timeline-item">
                      <span className="ghx-timeline-dot" aria-hidden="true">
                        {inc.sequence === 0 ? (
                          <BranchIcon />
                        ) : inc.status === "pushed" ? (
                          <PullRequestIcon />
                        ) : (
                          <IdeaIcon />
                        )}
                      </span>
                      <div className="ghx-timeline-body">
                        <span className="ghx-timeline-title">
                          {inc.sequence === 0 ? "Baseline" : `Increment ${inc.sequence}`}
                          {inc.title ? ` · ${inc.title}` : ""}
                        </span>
                        <span className="ghx-timeline-meta">
                          {INCREMENT_STATUS_LABEL[inc.status]}
                          {formatWhen(inc.created_at) &&
                            ` · ${formatWhen(inc.created_at)}`}
                        </span>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            )}

            {outOfSync && !syncPaused && (
              <div className="ghx-notice ghx-notice-drift" role="status">
                <span className="ghx-notice-icon" aria-hidden="true">
                  <DriftIcon />
                </span>
                <span>
                  Your Tasks changed since the last push — the issues on GitHub
                  may be stale. Re-sync to bring them in step.
                </span>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}

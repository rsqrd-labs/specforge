import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"

import type { SyncState, TaskSyncState } from "../../types/github"
import { ShippedCheckIcon } from "../shared/icons"
import { SyncStatusBanner } from "./SyncStatusBanner"

/*
 * TaskCompletionPanel — the frontend payoff of the GitHub loop (T-275).
 *
 * Moment-of-use feeling: the developer glances mid-build and feels the project
 * *breathing* — work they did on GitHub is reflected here without lifting a
 * finger. Calm confidence, a sibling of CoveragePanel / TaskValidationPanel —
 * not a new visual language.
 *
 * Layout sketch:
 *   ┌ ws-panel-section ───────────────────────────────┐
 *   │ TASK COMPLETION                    9 of 14 shipped│  ← label + count
 *   │ ▓▓▓▓▓▓▓▓▓░░░░░  (thin saffron fill, eases on flip)│  ← the hero
 *   │ [ drift banner — only when out_of_sync ]          │
 *   │ ◍ T-001  via PR        View issue →               │  ← quiet rows
 *   │ ◍ T-002  closed        View issue →               │
 *   └───────────────────────────────────────────────────┘
 *
 * Visual hierarchy: the progress *fill* is the hero (saffron), the fraction is
 * secondary, the rows are quiet; lotus appears once, only on a merged-PR check.
 * The one delight: when a task flips open→done between polls, its row does a
 * single gentle saffron-tinted highlight-and-settle — once, never looping.
 */

/** "connected" drives the live panel; the others fold to the paused line. */
export type SyncConnection = "connected" | "suspended" | "disconnected"

/* The side panel is a *glance*, not the ledger: it shows a capped window of
 * tasks (newest completions first, so a fresh open→done flash surfaces at the
 * top of the window) and defers the full list to the dedicated GitHub status
 * screen via `detailHref`. A completion that is older than a cap's worth of more
 * recent ones (e.g. a historical issue resurfacing via backfill) can fall
 * outside the window and not flash — it is still counted and shown on the detail
 * screen. Without a detail screen to defer to, it shows every task (the aside
 * scrolls — the panel no longer clips). */
const MAX_VISIBLE_TASKS = 6

interface TaskCompletionPanelProps {
  data: SyncState | null
  repoFullName: string | null
  repoUrl: string | null
  connection: SyncConnection
  loading: boolean
  resyncing: boolean
  onResync: () => void
  disabled?: boolean
  disabledReason?: string
  /** When set, the panel shows a "full status →" link to the dedicated GitHub
   *  export screen. The side panel is the glance; the screen is the detail. */
  detailHref?: string
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

function doneSet(tasks: TaskSyncState[]): Set<string> {
  return new Set(tasks.filter((t) => t.state === "done").map((t) => t.task_ref))
}

export function TaskCompletionPanel({
  data,
  repoFullName,
  repoUrl,
  connection,
  loading,
  resyncing,
  onResync,
  disabled = false,
  disabledReason,
  detailHref,
}: TaskCompletionPanelProps) {
  // One-time highlight of rows that flip open→done between refetches. The ref is
  // seeded from the FIRST fetch so already-shipped rows never flash on mount —
  // only true transitions do.
  const previouslyDone = useRef<Set<string> | null>(null)
  const [justShipped, setJustShipped] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!data) return
    const current = doneSet(data.tasks)
    const previous = previouslyDone.current
    previouslyDone.current = current
    if (previous === null) return // first load — establish the baseline, no flash
    const newly = [...current].filter((ref) => !previous.has(ref))
    if (newly.length === 0) return
    setJustShipped(new Set(newly))
    const handle = window.setTimeout(() => setJustShipped(new Set()), 1400)
    return () => window.clearTimeout(handle)
  }, [data])

  // Loading the first time — a tasteful skeleton of two rows, never a spinner.
  if (loading && !data) {
    return (
      <div className="ws-panel-section ws-sync-panel" aria-busy="true">
        <div className="ws-panel-title">Task completion</div>
        <div className="ws-sync-skeleton" aria-hidden="true">
          <span className="ws-sync-skeleton-bar" />
          <span className="ws-sync-skeleton-row" />
          <span className="ws-sync-skeleton-row" />
        </div>
      </div>
    )
  }

  // Not a GitHub-connected workspace (never pushed) — show nothing.
  if (!data) return null

  // The install was suspended or removed — fold to a single calm slate line.
  if (connection !== "connected") {
    return (
      <div className="ws-panel-section ws-sync-panel">
        <div className="ws-panel-title">Task completion</div>
        <SyncStatusBanner variant="disconnected" />
      </div>
    )
  }

  const { shipped, total, out_of_sync, tasks } = data
  const pct = total > 0 ? Math.round((shipped / total) * 100) : 0
  const allShipped = total > 0 && shipped === total

  // Shipped tasks first (newest completion on top), then open tasks in issue
  // order — so the completion story leads and a task that just flipped open→done
  // surfaces at the top of the window and flashes (a completion older than the
  // visible window can still fall past the cap; see the panel note above).
  const orderedTasks = [...tasks].sort((a, b) => {
    const aDone = a.state === "done"
    const bDone = b.state === "done"
    if (aDone !== bDone) return aDone ? -1 : 1
    if (aDone && bDone) {
      const at = a.done_at ? Date.parse(a.done_at) : 0
      const bt = b.done_at ? Date.parse(b.done_at) : 0
      return bt - at
    }
    return a.issue_number - b.issue_number
  })
  // Only cap when there's a detail screen to send the overflow to; otherwise the
  // panel would silently hide tasks with no way to reach them.
  const visibleTasks = detailHref
    ? orderedTasks.slice(0, MAX_VISIBLE_TASKS)
    : orderedTasks
  const hiddenCount = tasks.length - visibleTasks.length

  return (
    <div className="ws-panel-section ws-sync-panel">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Task completion</div>
          <p>Issues close here as you ship them on GitHub.</p>
        </div>
        <span className="ws-sync-count" aria-hidden="true">
          {shipped} <span className="ws-sync-count-sep">of</span> {total}
        </span>
      </div>

      {/* The hero: a thin saffron fill; the header fraction is its label. */}
      <div
        className={`ws-sync-progress${allShipped ? " complete" : ""}`}
        role="progressbar"
        aria-valuenow={shipped}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={`${shipped} of ${total} tasks shipped`}
      >
        <span className="ws-sync-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {(total === 0 || allShipped) && (
        <p className="ws-sync-progress-caption">
          {total === 0 ? "No tasks to ship yet." : "Every task has shipped."}
        </p>
      )}

      {out_of_sync && (
        <SyncStatusBanner
          variant="drift"
          resyncing={resyncing}
          onResync={onResync}
          disabled={disabled}
          disabledReason={disabledReason}
        />
      )}

      {visibleTasks.length > 0 && (
        <ul className="ws-sync-task-list">
          {visibleTasks.map((task) => {
            const isDone = task.state === "done"
            const viaPr = task.done_via === "pr_merge"
            const href = issueHref(repoUrl, repoFullName, task.issue_number)
            const flash = justShipped.has(task.task_ref)
            // The opaque `task_ref` hash is never shown; fall back to the issue
            // number when a legacy/increment task has no resolved title.
            const heading = task.title ?? `Issue #${task.issue_number}`
            return (
              <li
                key={task.task_ref}
                className={[
                  "ws-sync-task",
                  isDone ? "done" : "open",
                  flash ? "just-shipped" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <span
                  className={`ws-sync-check${isDone ? " done" : ""}${
                    viaPr ? " via-pr" : ""
                  }`}
                  aria-hidden="true"
                >
                  <ShippedCheckIcon />
                </span>
                <span className="ws-sync-task-main">
                  <span className="ws-sync-task-heading">
                    {task.human_ref && (
                      <span className="ws-sync-task-ref">{task.human_ref}</span>
                    )}
                    <span className="ws-sync-task-title" title={heading}>
                      {heading}
                    </span>
                  </span>
                  {isDone && (
                    <span className="ws-sync-task-state">
                      {viaPr ? "Shipped via PR" : "Shipped"}
                    </span>
                  )}
                </span>
                {href && (
                  <a
                    className="ws-sync-task-link"
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Issue #${task.issue_number} on GitHub`}
                  >
                    {`#${task.issue_number} ↗`}
                  </a>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {detailHref && (
        <Link to={detailHref} className="ws-sync-detail-link">
          {hiddenCount > 0
            ? `View all ${total} tasks →`
            : "Open full GitHub status →"}
        </Link>
      )}
    </div>
  )
}

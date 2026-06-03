import { useEffect, useRef, useState } from "react"

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

interface TaskCompletionPanelProps {
  data: SyncState | null
  repoFullName: string | null
  repoUrl: string | null
  connection: SyncConnection
  loading: boolean
  resyncing: boolean
  onResync: () => void
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

      {/* The hero: a thin saffron fill, secondary fraction. */}
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
      <p className="ws-sync-progress-caption">
        {total === 0
          ? "No tasks to ship yet."
          : allShipped
            ? "Every task has shipped."
            : `${shipped} of ${total} tasks shipped`}
      </p>

      {out_of_sync && (
        <SyncStatusBanner
          variant="drift"
          resyncing={resyncing}
          onResync={onResync}
        />
      )}

      {tasks.length > 0 && (
        <ul className="ws-sync-task-list">
          {tasks.map((task) => {
            const isDone = task.state === "done"
            const viaPr = task.done_via === "pr_merge"
            const href = issueHref(repoUrl, repoFullName, task.issue_number)
            const flash = justShipped.has(task.task_ref)
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
                <span className="ws-sync-task-ref">{task.task_ref}</span>
                {isDone && (
                  <span className="ws-sync-task-via">
                    {viaPr ? "via PR" : "closed"}
                  </span>
                )}
                {href && (
                  <a
                    className="ws-sync-task-link"
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {`Issue #${task.issue_number} ↗`}
                  </a>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

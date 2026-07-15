import { useState } from "react"
import { exportWorkspace, getApiErrorMessage } from "../../services/api"
import { useWorkspaceStore } from "../../store/workspaceStore"
import type { TrashedWorkspace } from "../../types/retention"
import { ActionAlertPanel } from "../shared/ActionAlert"

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now()
  return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)))
}

function countdownLabel(purgeAfter: string): string {
  const days = daysUntil(purgeAfter)
  if (days <= 0) return "Deleting soon"
  if (days === 1) return "Deletes in 1 day"
  return `Deletes in ${days} days`
}

function slugFor(name: string, id: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || id
  )
}

/**
 * "Recently deleted" — the user-facing trash surface (issue #43, plan §5.4).
 * A collapsed section listing trashed workspaces with a per-card countdown plus
 * Restore and Export for the whole window. Renders nothing when the trash is
 * empty so it never adds noise to a clean dashboard.
 */
export function RecentlyDeletedSection() {
  const trashed = useWorkspaceStore((s) => s.trashedWorkspaces)
  const restoreWorkspace = useWorkspaceStore((s) => s.restoreWorkspace)
  const [expanded, setExpanded] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (trashed.length === 0) return null

  async function handleRestore(workspace: TrashedWorkspace) {
    if (busyId) return
    setBusyId(workspace.id)
    setError(null)
    try {
      await restoreWorkspace(workspace.id)
    } catch (exc) {
      setError(getApiErrorMessage(exc, "Could not restore this workspace."))
    } finally {
      setBusyId(null)
    }
  }

  async function handleExport(workspace: TrashedWorkspace) {
    if (busyId) return
    setBusyId(workspace.id)
    setError(null)
    try {
      const blob = await exportWorkspace(workspace.id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `specforge-${slugFor(workspace.name, workspace.id)}.zip`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1_500)
    } catch (exc) {
      setError(
        getApiErrorMessage(
          exc,
          "Could not export this workspace. It may not be fully finalised.",
        ),
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="recently-deleted" aria-label="Recently deleted workspaces">
      <button
        type="button"
        className="recently-deleted-toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls="recently-deleted-list"
      >
        <span className="recently-deleted-toggle-icon" aria-hidden="true">
          🗑
        </span>
        <span>Recently deleted</span>
        <span className="recently-deleted-count">{trashed.length}</span>
        <span className="recently-deleted-chevron" aria-hidden="true">
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {expanded && (
        <div id="recently-deleted-list" className="recently-deleted-list">
          {error && (
            <ActionAlertPanel
              severity="error"
              title="Action failed"
              message={error}
              recovery="Try again."
              source="Recently deleted"
              onDismiss={() => setError(null)}
            />
          )}
          {trashed.map((workspace) => (
            <div key={workspace.id} className="recently-deleted-card">
              <div className="recently-deleted-card-main">
                <strong className="recently-deleted-card-name">
                  {workspace.name}
                </strong>
                <span className="recently-deleted-card-meta">
                  {countdownLabel(workspace.purge_after)}
                </span>
              </div>
              <div className="recently-deleted-card-actions">
                <button
                  type="button"
                  className="recently-deleted-restore"
                  onClick={() => void handleRestore(workspace)}
                  disabled={busyId === workspace.id}
                >
                  {busyId === workspace.id ? "Working…" : "Restore"}
                </button>
                <button
                  type="button"
                  className="recently-deleted-export"
                  onClick={() => void handleExport(workspace)}
                  disabled={busyId === workspace.id}
                >
                  Export
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

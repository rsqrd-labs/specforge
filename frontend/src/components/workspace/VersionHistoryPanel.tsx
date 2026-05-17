import { useEffect, useState } from "react"

import { getStageVersions } from "../../services/api"
import type { Stage, StageVersion } from "../../types/stage"

interface VersionHistoryPanelProps {
  stage: Stage
  onRollback: (version: number) => Promise<void>
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
}

export function VersionHistoryPanel({ stage, onRollback }: VersionHistoryPanelProps) {
  const [versions, setVersions] = useState<StageVersion[] | null>(null)
  const [rolling, setRolling] = useState<number | null>(null)
  const [rollbackError, setRollbackError] = useState<string | null>(null)

  useEffect(() => {
    setVersions(null)
    getStageVersions(stage.id)
      .then(setVersions)
      .catch(() => setVersions([]))
  }, [stage.id, stage.current_version])

  if (!versions || versions.length <= 1) return null

  async function handleRollback(version: number) {
    setRolling(version)
    setRollbackError(null)
    try {
      await onRollback(version)
    } catch {
      setRollbackError("Restore failed — please try again.")
    } finally {
      setRolling(null)
    }
  }

  const isFinalised = stage.status === "finalised"

  return (
    <div className="ws-panel-section">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Version History</div>
          <p>
            {isFinalised
              ? "Finalised — restore a version to unlock regeneration."
              : "Restore a previous version of this stage."}
          </p>
        </div>
        <span className="ws-panel-chip">{versions.length} versions</span>
      </div>

      <ul className="ws-version-list">
        {versions.map((v) => {
          const isCurrent = v.version === stage.current_version
          return (
            <li key={v.id} className={`ws-version-item${isCurrent ? " current" : ""}`}>
              <div className="ws-version-meta">
                <span className="ws-version-number">v{v.version}</span>
                <span className="ws-version-by">{v.created_by === "ai" ? "AI" : "Edited"}</span>
                <span className="ws-version-date">{formatDate(v.created_at)}</span>
              </div>
              {isCurrent ? (
                <span className="ws-version-badge">Current</span>
              ) : (
                <button
                  type="button"
                  className="ws-version-restore-btn"
                  disabled={rolling !== null}
                  onClick={() => void handleRollback(v.version)}
                >
                  {rolling === v.version ? "Restoring…" : "Restore"}
                </button>
              )}
            </li>
          )
        })}
      </ul>

      {rollbackError && (
        <p className="ws-panel-muted" style={{ color: "#dc2626", marginTop: 8 }}>
          {rollbackError}
        </p>
      )}
    </div>
  )
}

import { useEffect, useState } from "react"

import { getStageVersions } from "../../services/api"
import type { ResearchSource, Stage, StageVersion } from "../../types/stage"

interface VersionHistoryPanelProps {
  stage: Stage
  onRollback: (version: number) => Promise<void>
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return url
  }
}

/**
 * Provenance for a version generated with Brave web research (issue #12, Phase 4).
 * Rendered only when the version actually carried grounding. Source URLs are
 * http/https-allowlisted server-side; we still set rel="noopener noreferrer" and
 * defend-in-depth by skipping any non-http(s) URL that somehow reaches the client.
 */
function ResearchProvenance({ sources }: { sources?: ResearchSource[] | null }) {
  const safe = (sources ?? []).filter((s) => /^https?:\/\//i.test(s.url))
  return (
    <div className="ws-version-research">
      <span className="ws-version-research-badge">Grounded with web research</span>
      {safe.length > 0 ? (
        <ul className="ws-version-research-sources">
          {safe.map((s) => (
            <li key={s.url}>
              <a href={s.url} target="_blank" rel="noopener noreferrer" title={s.title || s.url}>
                {hostnameOf(s.url)}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
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

  if (!versions) return null

  // The restore list only makes sense with 2+ versions, but a grounded *first*
  // generation (a single version) must still show its web-research provenance —
  // so we render the panel when either is true and gate each part below.
  const current = versions.find((v) => v.version === stage.current_version)
  const showHistory = versions.length > 1
  const currentGrounded = Boolean(current?.research_context)
  if (!showHistory && !currentGrounded) return null

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

  // Single grounded version: no restore UI yet, but surface the provenance so the
  // first grounded generation isn't silent. (Once 2+ versions exist the full
  // history list below renders each version's provenance inline.)
  if (!showHistory) {
    return (
      <div className="ws-panel-section">
        <div className="ws-panel-section-header">
          <div>
            <div className="ws-panel-title">Web research</div>
            <p>This generation was grounded in current web context.</p>
          </div>
        </div>
        <ResearchProvenance sources={current?.research_sources} />
      </div>
    )
  }

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
              <div className="ws-version-main">
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
              </div>
              {v.research_context ? <ResearchProvenance sources={v.research_sources} /> : null}
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

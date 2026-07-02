import { useEffect, useState } from "react"
import { getRetentionPolicy } from "../../services/api"
import type { RetentionPolicy } from "../../types/retention"

/**
 * "Data retention" settings panel (issue #43, plan §5.4). Renders the live
 * retention windows from GET /retention/policy so users can see how long
 * deleted workspaces, version history, and telemetry are kept. Read-only.
 */
export default function DataRetentionPanel() {
  const [policy, setPolicy] = useState<RetentionPolicy | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getRetentionPolicy()
      .then((p) => {
        setPolicy(p)
        setFailed(false)
      })
      .catch(() => setFailed(true))
  }, [])

  return (
    <div className="data-retention-panel">
      <h2 className="settings-section-title">Data retention</h2>
      <p className="settings-section-copy">
        How long SpecForge keeps your data. Deleting a workspace moves it to the
        trash, where you can restore or export it before it is permanently
        removed.
      </p>

      {failed ? (
        <p className="settings-section-copy">
          Retention details are unavailable right now.
        </p>
      ) : policy === null ? (
        <p className="settings-section-copy">Loading retention details…</p>
      ) : (
        <dl className="data-retention-list">
          <div className="data-retention-row">
            <dt>Trash window</dt>
            <dd>
              {policy.trash_days} days after you delete a workspace (restore or
              export anytime before then)
            </dd>
          </div>
          <div className="data-retention-row">
            <dt>Version history</dt>
            <dd>
              The most recent {policy.stage_versions_keep} versions of each stage
              are always kept; older ones are pruned after{" "}
              {policy.stage_versions_min_age_days} days
            </dd>
          </div>
          <div className="data-retention-row">
            <dt>Keynotes</dt>
            <dd>
              The most recent {policy.storyboards_keep} keynotes per workspace are
              kept; older ones are pruned after {policy.storyboards_min_age_days}{" "}
              days
            </dd>
          </div>
          <div className="data-retention-row">
            <dt>Usage telemetry</dt>
            <dd>Internal cost and quality logs are kept for {policy.cost_events_days} days</dd>
          </div>
        </dl>
      )}

      <a
        className="data-retention-policy-link"
        href="https://specforge.dev/legal/retention"
        target="_blank"
        rel="noreferrer noopener"
      >
        Read the full data retention policy →
      </a>
    </div>
  )
}

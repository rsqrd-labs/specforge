import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getRetentionPolicy } from "../../services/api"
import type { RetentionPolicy } from "../../types/retention"

/**
 * "Data retention" settings panel (issue #43, plan §5.4). Renders the live
 * retention windows from GET /retention/policy so users can see how long
 * deleted workspaces, version history, and telemetry are kept. Read-only.
 *
 * Presentation: a scannable list where each window leads with its headline
 * number (a saffron value chip) and a one-line plain-language explanation.
 */

interface RetentionRow {
  key: string
  term: string
  value: string
  unit: string
  desc: string
}

function buildRows(policy: RetentionPolicy): RetentionRow[] {
  return [
    {
      key: "trash",
      term: "Trash window",
      value: String(policy.trash_days),
      unit: "days",
      desc: "A deleted workspace waits in the trash this long — restore or export it anytime before it's permanently removed.",
    },
    {
      key: "versions",
      term: "Version history",
      value: String(policy.stage_versions_keep),
      unit: "kept",
      desc: `The latest versions of each stage are always kept; older ones are pruned after ${policy.stage_versions_min_age_days} days.`,
    },
    {
      key: "keynotes",
      term: "Keynotes",
      value: String(policy.storyboards_keep),
      unit: "kept",
      desc: `The latest keynotes per workspace are kept; older ones are pruned after ${policy.storyboards_min_age_days} days.`,
    },
    {
      key: "telemetry",
      term: "Usage telemetry",
      value: String(policy.cost_events_days),
      unit: "days",
      desc: "Internal cost and quality logs we keep to monitor product health.",
    },
  ]
}

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
      <div className="settings-panel-header">
        <span className="settings-panel-icon" aria-hidden="true">
          <RetentionIcon />
        </span>
        <div className="settings-panel-heading">
          <h2 className="settings-section-title">Data retention</h2>
          <p className="settings-section-copy">
            How long SpecForge keeps your data. Nothing here is billed or
            configurable — it's shown so you always know what's stored and for
            how long.
          </p>
        </div>
      </div>

      {failed ? (
        <p className="data-retention-status" role="status">
          Retention details are unavailable right now.
        </p>
      ) : policy === null ? (
        <div className="data-retention-skeleton" aria-hidden="true">
          <span className="data-retention-skeleton-row" />
          <span className="data-retention-skeleton-row" />
          <span className="data-retention-skeleton-row" />
          <span className="data-retention-skeleton-row" />
        </div>
      ) : (
        <dl className="data-retention-list">
          {buildRows(policy).map((row) => (
            <div className="data-retention-row" key={row.key}>
              <dt className="data-retention-term">
                <span className="data-retention-term-label">{row.term}</span>
                <span className="data-retention-value">
                  <strong>{row.value}</strong>
                  <span>{row.unit}</span>
                </span>
              </dt>
              <dd className="data-retention-desc">{row.desc}</dd>
            </div>
          ))}
        </dl>
      )}

      {/* Client-side navigation to the in-app policy pages: relative Links
          work on every origin the SPA is served from (localhost, staging,
          production), unlike a hardcoded absolute domain. Terms/Privacy are
          only reachable from the signed-out Landing page otherwise, so a
          signed-in user needs a way to get back to them too. */}
      <div className="data-retention-links">
        <Link className="data-retention-policy-link" to="/legal/retention">
          Data retention policy
          <span aria-hidden="true">→</span>
        </Link>
        <Link className="data-retention-policy-link" to="/legal/terms">
          Terms of Service
          <span aria-hidden="true">→</span>
        </Link>
        <Link className="data-retention-policy-link" to="/legal/privacy">
          Privacy Policy
          <span aria-hidden="true">→</span>
        </Link>
      </div>
    </div>
  )
}

function RetentionIcon() {
  // A clock in a shield — "kept safely, for a bounded time".
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2.75 4.75 5.5v5.2c0 4.36 2.94 8.36 7.25 9.55 4.31-1.19 7.25-5.19 7.25-9.55V5.5L12 2.75Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="11" r="3.4" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M12 9.4V11l1.15 1.15"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

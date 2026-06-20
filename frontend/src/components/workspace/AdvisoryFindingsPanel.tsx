import { useState } from "react"
import type { QualityGateFinding, StageType } from "../../types/stage"
import { findingKindLabel } from "../../utils/qualityGate"

interface AdvisoryFindingsPanelProps {
  /** The non-blocking critic suggestions for the current draft. */
  findings: QualityGateFinding[]
  /** Stage these suggestions belong to, for the heading copy. */
  stageType: StageType
  /** Regenerate the stage to try to address the suggestions. */
  onRegenerate?: () => void
  /** Disable actions while a workspace-level mutation holds the lock. */
  actionsDisabled?: boolean
  /** Reason the actions are disabled (shown as a note + tooltip). */
  disabledReason?: string
}

/** Non-blocking "suggestions" surface for a delivered, finalisable draft whose
 *  LLM quality review left findings (issue #34). Unlike the blocking quality-gate
 *  panel this never stops finalisation — it makes clear the draft is ready and
 *  the findings are optional improvements. Reads from the persisted
 *  `Stage.quality_gate` (status="advisory"), so it survives refresh and is not
 *  tied to a transient stream event. */
export function AdvisoryFindingsPanel({
  findings,
  stageType,
  onRegenerate,
  actionsDisabled = false,
  disabledReason,
}: AdvisoryFindingsPanelProps) {
  const [collapsed, setCollapsed] = useState(false)
  if (findings.length === 0) return null

  const count = findings.length
  const disabledReasonId = disabledReason
    ? "advisory-findings-disabled-reason"
    : undefined

  if (collapsed) {
    return (
      <div className="quality-gate-collapsed" role="status">
        <div className="quality-gate-collapsed-text">
          <span className="workspace-advisory-chip">
            {count} suggestion{count === 1 ? "" : "s"}
          </span>
          <p className="quality-gate-collapsed-reason">
            This {stageType} is ready to finalise. The quality review left some
            optional suggestions.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setCollapsed(false)}
        >
          Show suggestions
        </button>
      </div>
    )
  }

  return (
    <div className="quality-gate-inline advisory" role="status" aria-label="Quality review suggestions">
      <div className="quality-gate-panel">
        <h3 className="quality-gate-title">
          This {stageType} is ready — {count} optional suggestion
          {count === 1 ? "" : "s"}
        </h3>
        <p className="quality-gate-subtitle">
          You can finalise this {stageType} now. These are improvements the
          quality review suggested — address them only if they matter to you.
        </p>
        <ul className="quality-gate-findings">
          {findings.map((finding, index) => (
            <li key={index} className="quality-gate-finding">
              <span className="quality-gate-kind">
                {findingKindLabel(finding.kind)}
              </span>
              {finding.reference ? (
                <span className="quality-gate-ref"> · {finding.reference}</span>
              ) : null}
              <span className="quality-gate-detail"> — {finding.detail}</span>
            </li>
          ))}
        </ul>
        <div className="quality-gate-actions">
          {actionsDisabled && disabledReason ? (
            <p id={disabledReasonId} className="workspace-lock-inline-note">
              {disabledReason}
            </p>
          ) : null}
          {onRegenerate ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onRegenerate}
              disabled={actionsDisabled}
              title={actionsDisabled ? disabledReason : undefined}
              aria-describedby={actionsDisabled ? disabledReasonId : undefined}
            >
              Regenerate to address
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setCollapsed(true)}
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}

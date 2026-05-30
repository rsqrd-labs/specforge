import type { QualityGateInfo } from "../../services/sseService"

interface StreamingOverlayProps {
  isVisible: boolean
  /** Critic quality-gate findings, present when a generation was held back
   *  by the gate (T-247).  Rendered as an interactive panel with regenerate
   *  and owner-only override actions. */
  gate?: QualityGateInfo
  /** Re-run generation for the stage (the failed artifact was not persisted). */
  onRegenerate?: () => void
  /** Owner escape hatch: disable the critic for this workspace, then regenerate. */
  onOverride?: () => void
  /** Dismiss the findings panel without acting. */
  onDismiss?: () => void
}

export function StreamingOverlay({
  isVisible,
  gate,
  onRegenerate,
  onOverride,
  onDismiss,
}: StreamingOverlayProps) {
  if (gate) {
    return (
      <div
        className="streaming-overlay quality-gate-overlay pointer-events-auto"
        role="alertdialog"
        aria-label="Quality gate findings"
      >
        <div className="quality-gate-panel">
          <h3 className="quality-gate-title">Quality gate held this generation back</h3>
          <p className="quality-gate-subtitle">
            The critic found {gate.findings.length}{" "}
            {gate.findings.length === 1 ? "issue" : "issues"} in the generated{" "}
            {gate.stage}. Regenerate to try again, or override to accept anyway.
          </p>
          <ul className="quality-gate-findings">
            {gate.findings.map((finding, index) => (
              <li key={index} className="quality-gate-finding">
                <span className="quality-gate-kind">{finding.kind}</span>
                {finding.reference ? (
                  <span className="quality-gate-ref"> · {finding.reference}</span>
                ) : null}
                <span className="quality-gate-detail"> — {finding.detail}</span>
              </li>
            ))}
          </ul>
          <div className="quality-gate-actions">
            {onRegenerate ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={onRegenerate}
              >
                Regenerate
              </button>
            ) : null}
            {onOverride ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onOverride}
              >
                Override and continue
              </button>
            ) : null}
            {onDismiss ? (
              <button type="button" className="btn btn-ghost" onClick={onDismiss}>
                Dismiss
              </button>
            ) : null}
          </div>
        </div>
      </div>
    )
  }

  if (!isVisible) return null

  return (
    <div className="streaming-overlay pointer-events-none">
      <div className="streaming-badge">
        <span className="streaming-cursor" />
        Generating…
      </div>
    </div>
  )
}

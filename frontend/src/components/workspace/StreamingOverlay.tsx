import type { QualityGateInfo } from "../../types/stage"

interface StreamingOverlayProps {
  isVisible: boolean
  /** Critic quality-gate findings, present when a generation was held back
   *  by the gate (T-247).  Rendered as an interactive panel with regenerate
   *  and owner-only override actions. */
  gate?: QualityGateInfo
  /** Re-run generation for the stage, replacing the blocked draft. */
  onRegenerate?: () => void
  /** Accept the current blocked draft without disabling the workspace critic. */
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
    const missing = gate.missing ?? []
    const findings = gate.findings ?? []
    const reasons = gate.reasons ?? []
    const isIncomplete = gate.kind === "incomplete_output"
    const isMissingSections = gate.kind === "missing_sections" || missing.length > 0
    const issueCount = isIncomplete
      ? reasons.length || findings.length
      : isMissingSections
        ? missing.length
        : findings.length
    const canOverride = gate.override_allowed !== false && !isIncomplete
    return (
      <div
        className="quality-gate-inline"
        role="alertdialog"
        aria-label="Quality gate findings"
      >
        <div className="quality-gate-panel">
          <h3 className="quality-gate-title">Quality gate held this generation back</h3>
          <p className="quality-gate-subtitle">
            {isIncomplete
              ? `The generated ${gate.stage} stopped before completion${
                  gate.repair_attempted ? " after a repair attempt" : ""
                }. Regenerate to produce a complete version.`
              : isMissingSections
              ? `The generated ${gate.stage} is missing ${issueCount} required ${
                  issueCount === 1 ? "section" : "sections"
                }. Regenerate to try again, or override to accept anyway.`
              : `The critic found ${issueCount} ${
                  issueCount === 1 ? "issue" : "issues"
                } in the generated ${gate.stage}. Regenerate to try again, or override to accept anyway.`}
          </p>
          {isIncomplete ? (
            <ul className="quality-gate-findings">
              {(reasons.length ? reasons : findings).map((reason, index) => (
                <li key={index} className="quality-gate-finding">
                  <span className="quality-gate-kind">
                    {"code" in reason ? reason.code : reason.kind}
                  </span>
                  {reason.reference ? (
                    <span className="quality-gate-ref"> · {reason.reference}</span>
                  ) : null}
                  <span className="quality-gate-detail"> — {reason.detail}</span>
                </li>
              ))}
            </ul>
          ) : isMissingSections ? (
            <ul className="quality-gate-findings">
              {missing.map((heading) => (
                <li key={heading} className="quality-gate-finding">
                  <span className="quality-gate-kind">MissingSection</span>
                  <span className="quality-gate-detail"> — {heading}</span>
                </li>
              ))}
            </ul>
          ) : (
            <ul className="quality-gate-findings">
              {findings.map((finding, index) => (
                <li key={index} className="quality-gate-finding">
                  <span className="quality-gate-kind">{finding.kind}</span>
                  {finding.reference ? (
                    <span className="quality-gate-ref"> · {finding.reference}</span>
                  ) : null}
                  <span className="quality-gate-detail"> — {finding.detail}</span>
                </li>
              ))}
            </ul>
          )}
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
            {onOverride && canOverride ? (
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

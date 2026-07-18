import type { EvalResult, Stage } from "../../types/stage"

interface CoveragePanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
  onRegenerate: () => void
  disabled?: boolean
  disabledReason?: string
}

export function CoveragePanel({
  stage,
  evalResult,
  onRegenerate,
  disabled = false,
  disabledReason,
}: CoveragePanelProps) {
  if (stage.type !== "harness") return null

  // Coverage gaps on the HARNESS screen are derived ONLY from deferred_reqs — the
  // deterministic matrix→file integrity set (requirement IDs whose every mapped
  // test file is genuinely absent from the harness). The eval judge's
  // `uncovered_reqs` is intentionally NOT shown here: the judge scores a harness
  // compacted to ~20K chars, so on a normal 60–120KB harness it reports reqs
  // whose tests it simply could not see — a flood of phantom "missing coverage"
  // that eroded trust and could never clear. That list stays on the eval payload
  // for scoring/telemetry, but the gap panel and the paid patch are matrix-driven.
  const deferredReqs = evalResult?.deferred_reqs ?? []
  const regenerateHelpId = `${stage.id}-coverage-regenerate-help`
  const disabledReasonId = `${stage.id}-coverage-disabled-reason`

  if (!evalResult || deferredReqs.length === 0) {
    return null
  }

  return (
    <div className="ws-panel-section ws-coverage-card ws-coverage-card--gap">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Missing Test Coverage</div>
          <p>
            The test matrix maps these requirements to a test file that was not
            generated in the harness. Regenerate to fill in the missing tests.
          </p>
        </div>
        <span className="ws-panel-chip warning">
          {deferredReqs.length} missing
        </span>
      </div>

      <ul className="ws-issue-list">
        {deferredReqs.map((req) => (
          <li key={req} className="ws-issue-item">
            <div className="ws-issue-title">{req}</div>
          </li>
        ))}
      </ul>

      <button
        className="ws-action-btn"
        onClick={onRegenerate}
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        aria-label="Regenerate HARNESS"
        aria-describedby={`${regenerateHelpId}${disabled && disabledReason ? ` ${disabledReasonId}` : ""}`}
      >
        Regenerate
      </button>

      <p id={regenerateHelpId} className="ws-panel-muted">
        This regeneration costs 10 credits. It generates tests for the
        requirements above in one pass. If genuine gaps remain afterwards, your
        Plan needs more detail — use Refine on the Plan, then regenerate.
      </p>
      {disabled && disabledReason ? (
        <p id={disabledReasonId} className="workspace-lock-inline-note">
          {disabledReason}
        </p>
      ) : null}
    </div>
  )
}

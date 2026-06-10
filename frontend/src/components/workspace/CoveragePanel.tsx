import type { EvalResult, Stage } from "../../types/stage"

interface CoveragePanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
  freeRegenUsed: boolean
  onRegenerate: () => void
  disabled?: boolean
  disabledReason?: string
}

export function CoveragePanel({
  stage,
  evalResult,
  freeRegenUsed,
  onRegenerate,
  disabled = false,
  disabledReason,
}: CoveragePanelProps) {
  if (stage.type !== "harness") return null

  const uncoveredReqs = evalResult?.uncovered_reqs ?? []
  const regenerateHelpId = `${stage.id}-coverage-regenerate-help`
  const disabledReasonId = `${stage.id}-coverage-disabled-reason`

  if (!evalResult || uncoveredReqs.length === 0) return null

  return (
    <div className="ws-panel-section">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Coverage Gaps</div>
          <p>These requirements have no tests in the harness.</p>
        </div>
        <span className="ws-panel-chip warning">
          {uncoveredReqs.length} gap{uncoveredReqs.length !== 1 ? "s" : ""}
        </span>
      </div>

      <ul className="ws-issue-list">
        {uncoveredReqs.map((req) => (
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
        {freeRegenUsed
          ? "This regeneration costs 10 credits. These gaps are genuine — the harness cannot infer them from the current Plan. Refine the Plan to add the missing context, then regenerate."
          : "This regeneration is free. These gaps are on us. If gaps remain afterwards, your Plan needs more detail — use Refine on the Plan to add the missing context, then regenerate."}
      </p>
      {disabled && disabledReason ? (
        <p id={disabledReasonId} className="workspace-lock-inline-note">
          {disabledReason}
        </p>
      ) : null}
    </div>
  )
}

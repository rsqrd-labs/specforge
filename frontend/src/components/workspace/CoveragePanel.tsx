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

  const uncoveredReqs = evalResult?.uncovered_reqs ?? []
  // Deferred reqs are an optional, paid expansion beyond the baseline harness
  // (they never flag the eval). The harness patch covers them too — so the panel
  // renders and the button lights even when uncovered_reqs is empty. The backend
  // unions both sets.
  const deferredReqs = evalResult?.deferred_reqs ?? []
  const regenerateHelpId = `${stage.id}-coverage-regenerate-help`
  const disabledReasonId = `${stage.id}-coverage-disabled-reason`

  if (!evalResult || (uncoveredReqs.length === 0 && deferredReqs.length === 0)) {
    return null
  }

  return (
    <div className="ws-panel-section">
      {uncoveredReqs.length > 0 && (
        <>
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
        </>
      )}

      {deferredReqs.length > 0 && (
        <>
          <div className="ws-panel-section-header">
            <div>
              <div className="ws-panel-title">Expand Test Coverage</div>
              <p>
                Add deeper, dedicated tests for these requirements to go beyond
                the baseline harness — generate them whenever you want more
                exhaustive coverage.
              </p>
            </div>
            <span className="ws-panel-chip">{deferredReqs.length} optional</span>
          </div>

          <ul className="ws-issue-list">
            {deferredReqs.map((req) => (
              <li key={req} className="ws-issue-item">
                <div className="ws-issue-title">{req}</div>
              </li>
            ))}
          </ul>
        </>
      )}

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

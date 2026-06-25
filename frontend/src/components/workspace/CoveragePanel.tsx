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
  // deferred_reqs are now genuine, deterministic coverage holes: requirements
  // the test matrix maps to a test file that was never emitted in the harness
  // (matrix→file integrity). They are real gaps to fill, NOT an optional "beyond
  // baseline" upsell — the paid patch regenerates the missing tests. The backend
  // unions them with any LLM-derived uncovered_reqs for the patch.
  const deferredReqs = evalResult?.deferred_reqs ?? []
  const regenerateHelpId = `${stage.id}-coverage-regenerate-help`
  const disabledReasonId = `${stage.id}-coverage-disabled-reason`

  if (!evalResult || (uncoveredReqs.length === 0 && deferredReqs.length === 0)) {
    return null
  }

  return (
    <div
      className={`ws-panel-section ws-coverage-card ${
        uncoveredReqs.length > 0 || deferredReqs.length > 0
          ? "ws-coverage-card--gap"
          : "ws-coverage-card--deferred"
      }`}
    >
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
              <div className="ws-panel-title">Missing Test Coverage</div>
              <p>
                The test matrix maps these requirements to a test file that was
                not generated in the harness. Regenerate to fill in the missing
                tests.
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

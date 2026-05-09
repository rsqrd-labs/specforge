import type { EvalResult, Stage } from "../../types/stage"

interface CoveragePanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
}

export function CoveragePanel({ stage, evalResult }: CoveragePanelProps) {
  if (stage.type !== "harness") return null

  const coverage = evalResult?.coverage_percent
  const uncoveredReqs = evalResult?.uncovered_reqs ?? []
  const isLow = coverage !== null && coverage !== undefined && coverage < 80

  return (
    <div className="ws-panel-section">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Coverage</div>
          <p>Harness coverage across requirements.</p>
        </div>
        {coverage !== null && coverage !== undefined && (
          <span className={`ws-panel-chip ${isLow ? "warning" : "success"}`}>
            {coverage}%
          </span>
        )}
      </div>

      {coverage === null || coverage === undefined && (
        <p className="ws-panel-muted">Evaluating requirement coverage...</p>
      )}

      {coverage !== null && coverage !== undefined && (
        <div className="ws-progress-track">
          <div
            className={`ws-progress-fill ${isLow ? "low" : "good"}`}
            style={{ width: `${coverage}%` }}
          />
        </div>
      )}

      {uncoveredReqs.length > 0 && (
        <ul className="ws-issue-list">
          {uncoveredReqs.map((req) => (
            <li key={req} className="ws-issue-item">
              <div className="ws-issue-title">{req}</div>
            </li>
          ))}
        </ul>
      )}

      {coverage !== null && coverage !== undefined && !isLow && (
        <p className="ws-panel-ok">Full coverage</p>
      )}
    </div>
  )
}

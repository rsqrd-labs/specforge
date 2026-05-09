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
      <div className="ws-panel-title">Coverage</div>

      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 13 }}>
        <span style={{ color: "var(--color-on-surface-variant)" }}>
          {coverage === null || coverage === undefined ? "Evaluating…" : "Requirement coverage"}
        </span>
        {coverage !== null && coverage !== undefined && (
          <span style={{ fontWeight: 700, color: isLow ? "#dc2626" : "#16a34a" }}>
            {coverage}%
          </span>
        )}
      </div>

      {coverage !== null && coverage !== undefined && (
        <div className="ws-progress-track">
          <div
            className={`ws-progress-fill ${isLow ? "low" : "good"}`}
            style={{ width: `${coverage}%` }}
          />
        </div>
      )}

      {uncoveredReqs.length > 0 && (
        <ul style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
          {uncoveredReqs.map((req) => (
            <li key={req} className="ws-issue-item">
              <div className="ws-issue-title">{req}</div>
            </li>
          ))}
        </ul>
      )}

      {coverage !== null && coverage !== undefined && !isLow && (
        <p className="ws-panel-ok" style={{ marginTop: 8 }}>✓ Full coverage</p>
      )}
    </div>
  )
}

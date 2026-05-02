import type { EvalResult, Stage } from "../../types/stage"

interface CoveragePanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
}

export function CoveragePanel({ stage, evalResult }: CoveragePanelProps) {
  if (stage.type !== "harness") {
    return null
  }

  const coverage = evalResult?.coverage_percent
  const uncoveredReqs = evalResult?.uncovered_reqs ?? []
  const hasLowCoverage = coverage !== null && coverage !== undefined && coverage < 80

  return (
    <section className="border-b border-outline-variant bg-surface px-4 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-on-surface">Coverage</h2>
        <span className="text-sm font-medium text-on-surface-variant">
          {coverage === null || coverage === undefined
            ? "Evaluating..."
            : `${coverage}%`}
        </span>
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-surface-container-highest">
        <div
          className={`h-full rounded-full transition-all ${
            hasLowCoverage ? "bg-secondary" : "bg-green-500"
          }`}
          style={{ width: `${coverage ?? 0}%` }}
        />
      </div>

      {hasLowCoverage && uncoveredReqs.length > 0 && (
        <ul className="mt-3 space-y-2">
          {uncoveredReqs.map((requirement) => (
            <li
              key={requirement}
              className="rounded-lg border border-primary-container/40 bg-primary-container/10 px-3 py-2 text-sm text-on-primary-container"
            >
              {requirement}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

import type { EvalResult } from "../../types/stage"

interface QualityBadgeProps {
  evalResult: EvalResult | null | undefined
}

function scoreClasses(score: number): string {
  if (score >= 80) {
    return "border-green-200 bg-green-50 text-green-700"
  }
  if (score >= 60) {
    return "border-tertiary-container/60 bg-tertiary-container/20 text-on-tertiary-container"
  }
  return "border-error/30 bg-error-container text-on-error-container"
}

export function QualityBadge({ evalResult }: QualityBadgeProps) {
  const score = evalResult?.overall_score

  if (score === null || score === undefined) {
    return (
      <span className="inline-flex h-8 items-center rounded-full border border-outline-variant bg-surface-container-low px-3 text-xs font-medium text-on-surface-variant">
        Evaluating...
      </span>
    )
  }

  return (
    <span
      className={`inline-flex h-8 items-center rounded-full border px-3 text-xs font-semibold ${scoreClasses(score)}`}
    >
      {score}/100
    </span>
  )
}

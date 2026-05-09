import type { EvalResult } from "../../types/stage"

interface QualityBadgeProps {
  evalResult: EvalResult | null | undefined
}

export function QualityBadge({ evalResult }: QualityBadgeProps) {
  const score = evalResult?.overall_score

  if (score === null || score === undefined) {
    return (
      <span className="quality-badge pending">
        <span>Eval</span>
        <strong>--</strong>
      </span>
    )
  }

  const tier = score >= 80 ? "high" : score >= 60 ? "mid" : "low"
  return (
    <span className={`quality-badge ${tier}`}>
      <span>Eval</span>
      <strong>{score}/100</strong>
    </span>
  )
}

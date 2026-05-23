import type { EvalResult } from "../../types/stage"

interface QualityBadgeProps {
  evalResult: EvalResult | null | undefined
  /** Set to true when eval polling has exhausted all retries without success.
   *  Renders a grey "Score unavailable" badge instead of the shimmer spinner.
   *  M-5 — T-187.
   */
  error?: boolean
}

export function QualityBadge({ evalResult, error }: QualityBadgeProps) {
  // Terminal polling failure — show a deterministic fallback so users are not
  // left staring at an infinite shimmer.  M-5 — T-187.
  if (error) {
    return (
      <span className="quality-badge unavailable">
        <span>Eval</span>
        <strong>Score unavailable</strong>
      </span>
    )
  }

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

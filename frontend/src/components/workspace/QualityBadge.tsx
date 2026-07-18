import type { EvalResult } from "../../types/stage"

export type QualityStatus = "ready" | "attention" | "checking" | "unavailable"

interface QualityBadgeProps {
  evalResult: EvalResult | null | undefined
  /** Eval validation could not complete (e.g. the best-effort judge score
   *  failed). Renders a quiet, non-blocking "Unavailable" status rather than an
   *  infinite shimmer. */
  error?: boolean
  /** The stage is generating/validating and no eval has arrived yet. */
  checking?: boolean
}

export const QUALITY_STATUS_LABEL: Record<QualityStatus, string> = {
  ready: "Ready",
  attention: "Needs attention",
  checking: "Checking",
  unavailable: "Unavailable",
}

/** gap_type values that never move the badge — non-blocking or hidden:
 *  GENERATION_FAILURE (hidden prompt-quality issue), DEFERRED_COVERAGE (the
 *  harness recorded the category as deferred under budget), and
 *  UNVERIFIED_COVERAGE (the referenced file exists but its tests could not be
 *  parsed — a checker limitation, not a confirmed gap). */
const NON_ACTIONABLE_GAP_TYPES = new Set([
  "GENERATION_FAILURE",
  "DEFERRED_COVERAGE",
  "UNVERIFIED_COVERAGE",
])

/** Whether an eval carries a concrete, user-actionable gap. `flagged` already
 *  encodes harness coverage < 80 and genuine task gaps; the deterministic
 *  `deferred_reqs` (matrix→file holes) and genuine task issues are checked
 *  explicitly so a real gap is never missed. The judge's `uncovered_reqs` is
 *  deliberately NOT used — it is truncation-poisoned on a normal-size harness
 *  (issue: false coverage gaps, D-1) and would flood the badge with phantoms. */
export function hasActionableFindings(evalResult: EvalResult): boolean {
  if (evalResult.flagged) return true
  if ((evalResult.deferred_reqs?.length ?? 0) > 0) return true
  return (evalResult.tasks_without_ref ?? []).some(
    (issue) => !issue.gap_type || !NON_ACTIONABLE_GAP_TYPES.has(issue.gap_type),
  )
}

/** Findings-derived quality status (issue #27 Phase 1, Decision C). Users no
 *  longer see a numeric score; the primary signal is an actionable status
 *  derived from deterministic findings, not `overall_score`. Returns null when
 *  there is nothing to show (no eval and nothing in flight). */
export function deriveQualityStatus(
  evalResult: EvalResult | null | undefined,
  opts: { error?: boolean; checking?: boolean } = {},
): QualityStatus | null {
  if (opts.error) return "unavailable"
  if (evalResult) {
    return hasActionableFindings(evalResult) ? "attention" : "ready"
  }
  if (opts.checking) return "checking"
  return null
}

export function QualityBadge({ evalResult, error, checking }: QualityBadgeProps) {
  const status = deriveQualityStatus(evalResult, { error, checking })
  if (status === null) return null
  return (
    <span className={`quality-badge ${status}`} role="status">
      <span>Quality</span>
      <strong>{QUALITY_STATUS_LABEL[status]}</strong>
    </span>
  )
}

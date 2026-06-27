import type { Stage } from "../../types/stage"
import type { ConstructionVerdict } from "../../types/workspace"
import {
  deriveConstructionStatus,
  gapCount,
} from "../../utils/constructionVerdict"

interface ConstructionVerifiedBadgeProps {
  /** The persisted Demo Day construction verdict (null until it first runs). */
  verdict: ConstructionVerdict | null | undefined
  /** Live stages — their `current_version`s decide staleness. */
  stages: Pick<Stage, "type" | "current_version">[]
}

const STATUS_LABEL: Record<"verified" | "stale", string> = {
  verified: "Build-ready ✓",
  stale: "Check out of date",
}

/**
 * Compact, inline status badge for a Demo Day package's construction verdict
 * (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md §7.2). Mirrors `QualityBadge`'s
 * shape (`role="status"`, label + strong value) so it reads as a sibling signal.
 *
 * The guarantee is **earned per package**: only a `verified` verdict that still
 * matches the live stage versions gets the green ✓. A `stale` verdict (a stage
 * was refined after the verdict was stamped) never renders green — it prompts a
 * re-run, which happens on export (plan §9.2). A package with gaps shows the gap
 * count. Renders nothing for a standard workspace (no verdict) before the
 * verifier has ever run — the handoff panel carries the "pending" copy instead.
 */
export function ConstructionVerifiedBadge({
  verdict,
  stages,
}: ConstructionVerifiedBadgeProps) {
  const status = deriveConstructionStatus(verdict, stages)
  // No verdict yet → stay quiet; the panel explains the pending state.
  if (status === "pending" || !verdict) return null

  if (status === "gaps") {
    const gaps = gapCount(verdict)
    return (
      <span className="construction-badge gaps" role="status">
        <span>Build</span>
        <strong>
          {gaps} gap{gaps === 1 ? "" : "s"}
        </strong>
      </span>
    )
  }

  return (
    <span className={`construction-badge ${status}`} role="status">
      <span>Construction</span>
      <strong>{STATUS_LABEL[status]}</strong>
    </span>
  )
}

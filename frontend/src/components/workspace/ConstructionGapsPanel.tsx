import type { Stage } from "../../types/stage"
import type { ConstructionVerdict } from "../../types/workspace"
import {
  checkLabel,
  deriveConstructionStatus,
  failingChecks,
  gapCount,
} from "../../utils/constructionVerdict"

interface ConstructionGapsPanelProps {
  /** The persisted construction verdict (null until the verifier first runs). */
  verdict: ConstructionVerdict | null | undefined
  /** Live stages — their `current_version`s decide staleness. */
  stages: Pick<Stage, "type" | "current_version">[]
}

/**
 * Standard-mode counterpart to `DemoDayHandoffPanel`: the surface that NAMES the
 * gaps the `ConstructionVerifiedBadge` counts.
 *
 * The verifier runs for standard workspaces too, and the badge renders for them,
 * but the only two places that ever listed the gaps — this panel's Demo Day
 * sibling and `CONSTRUCTION_REPORT.md` — were both gated on `mode == "demo_day"`.
 * A standard user therefore saw "Build 7 gaps" with nothing anywhere explaining
 * which seven. This closes that.
 *
 * Deliberately smaller than the Demo Day card: no bundle download (standard mode
 * has its own export controls), no build-time estimate (a Demo Day concept —
 * standard verdicts carry `null`). Renders nothing until a verdict exists, so it
 * never occupies space on a package the verifier has not seen.
 */
export function ConstructionGapsPanel({
  verdict,
  stages,
}: ConstructionGapsPanelProps) {
  const status = deriveConstructionStatus(verdict, stages)
  if (!verdict || status === "pending") return null

  const gaps = gapCount(verdict)
  const failing = failingChecks(verdict)

  const chip =
    status === "verified" ? (
      <span className="ws-panel-chip success">Verified ✓</span>
    ) : status === "stale" ? (
      <span className="ws-panel-chip warning">Out of date</span>
    ) : (
      <span className="ws-panel-chip warning">
        {gaps} gap{gaps === 1 ? "" : "s"}
      </span>
    )

  return (
    <div className="ws-panel-section ws-handoff-card">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Build Check</div>
          <p>
            {status === "verified"
              ? "Every requirement is claimed by a task, every harness test is built by one, and the build order checks out."
              : status === "stale"
                ? "A stage changed since the last check. It is re-run automatically when you export the package."
                : "These structural gaps were found between your spec, plan, harness, and tasks."}
          </p>
        </div>
        {chip}
      </div>

      {status === "gaps" && failing.length > 0 && (
        <ul className="ws-issue-list">
          {failing.map((check) => (
            <li key={check.id} className="ws-issue-item">
              <div className="ws-issue-title">{checkLabel(check.name)}</div>
              {check.gaps.map((gap, i) => (
                <div key={i} className="ws-issue-reason">
                  {gap}
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}

      <p className="ws-panel-muted">
        Advisory only — it never blocks finalise or export. The full report ships
        as CONSTRUCTION_REPORT.md in the export ZIP.
      </p>
    </div>
  )
}

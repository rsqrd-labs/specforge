import type { Stage } from "../../types/stage"
import type { ConstructionVerdict, TargetAgent } from "../../types/workspace"
import {
  deriveConstructionStatus,
  failingChecks,
  gapCount,
} from "../../utils/constructionVerdict"

interface DemoDayHandoffPanelProps {
  /** The persisted construction verdict (null until the verifier first runs). */
  verdict: ConstructionVerdict | null | undefined
  /** Live stages — decide staleness and whether the package is whole. */
  stages: Pick<Stage, "type" | "current_version">[]
  /** Coding agent the export manual is tuned for (selects the filename copy). */
  targetAgent?: TargetAgent | null
  /** Download the agent-ready ZIP bundle (manual + CONSTRUCTION_REPORT.md). */
  onDownloadBundle: () => void
  /** True while the bundle download is in flight. */
  downloading?: boolean
  /** Export needs all four stages finalised; disable + explain if not yet. */
  downloadDisabled?: boolean
  downloadDisabledReason?: string
}

/** Plain-language labels for the verifier's check ids (plan §7.1). The raw
 *  names (`dag_acyclic`, `ac_to_test`) read like internal tokens. */
const CHECK_LABELS: Record<string, string> = {
  dag_acyclic: "Task build order is acyclic",
  task_to_test: "Every task maps to a harness test",
  ac_to_test: "Every acceptance criterion has a test",
  e2e_reachable: "End-to-end smoke test is reachable",
}

const MANUAL_FILENAME: Record<TargetAgent, string> = {
  claude_code: "CLAUDE.md",
  codex: "AGENTS.md",
}

/** Format an advisory minute estimate as a friendly "~Xh Ym" / "~Xm" string. */
function formatMinutes(minutes: number): string {
  if (minutes < 60) return `~${minutes}m`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return mins === 0 ? `~${hours}h` : `~${hours}h ${mins}m`
}

/**
 * Right-rail handoff surface for a Demo Day workspace (plan §8). Reads the
 * persisted construction verdict (NOT `Stage.quality_gate` — that slot is owned
 * by the async-advisory critic, plan §7.3 note 1) and renders:
 *
 * - the construction status (verified ✓ / N gaps / pending / stale),
 * - the named gap list when the verifier found gaps,
 * - the advisory estimated build time vs the ≤5h target (never a guarantee),
 * - a staleness note when a stage changed after the verdict was stamped, and
 * - the agent-tuned bundle download (the existing ZIP export, which carries the
 *   operating manual + CONSTRUCTION_REPORT.md and re-runs the verdict server-side
 *   when stale, plan §7.3).
 *
 * Advisory by design (plan §3.1): it never blocks finalise or export.
 */
export function DemoDayHandoffPanel({
  verdict,
  stages,
  targetAgent,
  onDownloadBundle,
  downloading = false,
  downloadDisabled = false,
  downloadDisabledReason,
}: DemoDayHandoffPanelProps) {
  const status = deriveConstructionStatus(verdict, stages)
  const gaps = verdict ? gapCount(verdict) : 0
  const failing = verdict ? failingChecks(verdict) : []
  const manualFile = MANUAL_FILENAME[targetAgent ?? "claude_code"]
  const disabledReasonId = downloadDisabledReason
    ? "demo-day-download-disabled-reason"
    : undefined

  const chip =
    status === "verified" ? (
      <span className="ws-panel-chip success">Verified ✓</span>
    ) : status === "gaps" ? (
      <span className="ws-panel-chip warning">
        {gaps} gap{gaps === 1 ? "" : "s"}
      </span>
    ) : status === "stale" ? (
      <span className="ws-panel-chip warning">Out of date</span>
    ) : (
      <span className="ws-panel-chip">Pending</span>
    )

  return (
    <div className="ws-panel-section ws-handoff-card">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Build Handoff</div>
          <p>
            {status === "verified"
              ? "Every task has a test and the build order checks out — when those tests pass, the prototype does what your approved spec says."
              : status === "gaps"
                ? "The package ships with these build gaps named — fix them or hand off as-is."
                : status === "stale"
                  ? "A stage changed since the last check. The check is re-run automatically when you download the bundle."
                  : "Finalise all four stages to run the build check."}
          </p>
        </div>
        {chip}
      </div>

      {/* Named gap list (only when the verifier ran and found gaps). */}
      {status === "gaps" && failing.length > 0 && (
        <ul className="ws-issue-list">
          {failing.map((check) => (
            <li key={check.id} className="ws-issue-item">
              <div className="ws-issue-title">
                {CHECK_LABELS[check.name] ?? check.name}
              </div>
              {check.gaps.map((gap, i) => (
                <div key={i} className="ws-issue-reason">
                  {gap}
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}

      {/* Advisory build-time estimate (plan §2.2 — calibration, never certified). */}
      {verdict && (
        <p className="ws-handoff-estimate">
          {verdict.estimated_minutes !== null
            ? `Estimated build time ${formatMinutes(verdict.estimated_minutes)}`
            : "No per-task estimate available"}
          <span className="ws-handoff-estimate-target">
            {" "}
            (target ≤ {formatMinutes(verdict.time_budget_minutes)})
          </span>
        </p>
      )}

      <button
        className="ws-action-btn"
        onClick={onDownloadBundle}
        disabled={downloadDisabled || downloading}
        title={downloadDisabled ? downloadDisabledReason : undefined}
        aria-label={`Download handoff bundle for ${manualFile}`}
        aria-describedby={
          downloadDisabled && disabledReasonId ? disabledReasonId : undefined
        }
      >
        {downloading
          ? "Preparing bundle…"
          : `Download handoff bundle (${manualFile})`}
      </button>

      <p className="ws-panel-muted">
        The ZIP includes {manualFile}, the spec/plan/harness/tasks, and
        CONSTRUCTION_REPORT.md. Hand it to your agent and implement the tasks one
        by one.
      </p>
      {downloadDisabled && downloadDisabledReason ? (
        <p id={disabledReasonId} className="workspace-lock-inline-note">
          {downloadDisabledReason}
        </p>
      ) : null}
    </div>
  )
}

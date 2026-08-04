import type { EvalResult, Stage } from "../../types/stage"

interface CoveragePanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
  onRegenerate: () => void
  disabled?: boolean
  disabledReason?: string
}

export function CoveragePanel({
  stage,
  evalResult,
  onRegenerate,
  disabled = false,
  disabledReason,
}: CoveragePanelProps) {
  if (stage.type !== "harness") return null

  // Coverage gaps on the HARNESS screen are derived ONLY from deferred_reqs —
  // the deterministic set of SPEC requirement IDs with no emitted test file
  // (`uncovered_requirements`, scoped to the upstream FR/NFR/SEC set). That
  // scope matters: a requirement the harness's matrix never mentioned is a gap,
  // not an absence of evidence, and it is the same denominator the coverage
  // percentage uses — so the chip and this list cannot contradict each other.
  // The eval judge's
  // `uncovered_reqs` is intentionally NOT shown here: the judge scores a harness
  // compacted to ~20K chars, so on a normal 60–120KB harness it reports reqs
  // whose tests it simply could not see — a flood of phantom "missing coverage"
  // that eroded trust and could never clear. That list stays on the eval payload
  // for scoring/telemetry, but the gap panel and the paid patch are matrix-driven.
  const deferredReqs = evalResult?.deferred_reqs ?? []
  const regenerateHelpId = `${stage.id}-coverage-regenerate-help`
  const disabledReasonId = `${stage.id}-coverage-disabled-reason`

  if (!evalResult || deferredReqs.length === 0) {
    return null
  }

  return (
    <div className="ws-panel-section ws-coverage-card ws-coverage-card--gap">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Missing Test Coverage</div>
          <p>
            These requirements have no test file in the harness — either the
            test matrix maps them to a file that was never generated, or the
            matrix does not cover them at all. Patch coverage to fill in the
            missing tests.
          </p>
        </div>
        <span className="ws-panel-chip warning">
          {deferredReqs.length} missing
        </span>
      </div>

      <ul className="ws-issue-list">
        {deferredReqs.map((req) => (
          <li key={req} className="ws-issue-item">
            <div className="ws-issue-title">{req}</div>
          </li>
        ))}
      </ul>

      <button
        className="ws-action-btn"
        onClick={onRegenerate}
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        aria-label="Patch HARNESS coverage"
        aria-describedby={`${regenerateHelpId}${disabled && disabledReason ? ` ${disabledReasonId}` : ""}`}
      >
        Patch coverage
      </button>

      <p id={regenerateHelpId} className="ws-panel-muted">
        This patch costs 10 credits only when new test files are added. It generates
        tests for the requirements above in one pass. If genuine gaps remain
        afterwards, your Plan needs more detail — use Refine on the Plan, then patch
        coverage again.
      </p>
      {disabled && disabledReason ? (
        <p id={disabledReasonId} className="workspace-lock-inline-note">
          {disabledReason}
        </p>
      ) : null}
    </div>
  )
}

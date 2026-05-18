import type { EvalResult, Stage, TaskReferenceIssue } from "../../types/stage"

interface TaskValidationPanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
  onNavigateToHarness?: () => void
}

function isGenuineGap(issue: TaskReferenceIssue): boolean {
  return !issue.gap_type || issue.gap_type === "GENUINE_GAP"
}

export function TaskValidationPanel({
  stage,
  evalResult,
  onNavigateToHarness,
}: TaskValidationPanelProps) {
  if (stage.type !== "tasks") return null

  const allIssues = evalResult?.tasks_without_ref ?? []
  const genuineGaps = allIssues.filter(isGenuineGap)

  if (!evalResult) {
    return (
      <div className="ws-panel-section">
        <div className="ws-panel-section-header">
          <div className="ws-panel-title">Coverage Gaps</div>
        </div>
        <p className="ws-panel-muted">Checking task traceability…</p>
      </div>
    )
  }

  if (genuineGaps.length === 0) return null

  return (
    <div className="ws-panel-section">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Coverage Gaps</div>
          <p>
            {genuineGaps.length === 1
              ? "1 task references a test that doesn't exist in your harness."
              : `${genuineGaps.length} tasks reference tests that don't exist in your harness.`}
          </p>
        </div>
        <span className="ws-panel-chip warning">
          {genuineGaps.length} {genuineGaps.length === 1 ? "gap" : "gaps"}
        </span>
      </div>

      <ul className="ws-issue-list">
        {genuineGaps.map((issue) => (
          <li
            key={`${issue.task_number}-${issue.task_title}`}
            className="ws-issue-item ws-issue-gap"
          >
            <div className="ws-issue-title">
              T-{issue.task_number}: {issue.task_title}
            </div>
            <div className="ws-issue-reason">{issue.reason}</div>
            {issue.remediation && (
              <div className="ws-issue-remediation">{issue.remediation}</div>
            )}
            {onNavigateToHarness && (
              <button
                type="button"
                className="ws-issue-action"
                onClick={onNavigateToHarness}
              >
                Go to Harness →
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

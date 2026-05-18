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
        <div className="ws-panel-title">Coverage Gaps</div>
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
              ? "1 task references a test missing from your harness."
              : `${genuineGaps.length} tasks reference tests missing from your harness.`}
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

            {issue.harness_file && (
              <div className="ws-issue-file-tag">{issue.harness_file}</div>
            )}

            <div className="ws-issue-reason">{issue.remediation ?? issue.reason}</div>

            {issue.code_stub && (
              <pre className="ws-issue-code-stub">{issue.code_stub}</pre>
            )}

            {onNavigateToHarness && (
              <button
                type="button"
                className="ws-issue-action"
                onClick={onNavigateToHarness}
              >
                Open Harness →
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

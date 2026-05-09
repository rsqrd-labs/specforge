import type { EvalResult, Stage } from "../../types/stage"

interface TaskValidationPanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
}

export function TaskValidationPanel({ stage, evalResult }: TaskValidationPanelProps) {
  if (stage.type !== "tasks") return null

  const issues = evalResult?.tasks_without_ref ?? []

  return (
    <div className="ws-panel-section">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Task Validation</div>
          <p>Traceability between tasks and tests.</p>
        </div>
        {evalResult && (
          <span className={`ws-panel-chip ${issues.length === 0 ? "success" : "warning"}`}>
            {issues.length === 0 ? "All clear" : `${issues.length} flagged`}
          </span>
        )}
      </div>

      {!evalResult && (
        <p className="ws-panel-muted">Evaluating task references...</p>
      )}

      {evalResult && issues.length === 0 && (
        <p className="ws-panel-ok">Every task references a test.</p>
      )}

      {issues.length > 0 && (
        <ul className="ws-issue-list">
          {issues.map((issue) => (
            <li key={`${issue.task_number}-${issue.task_title}`} className="ws-issue-item">
              <div className="ws-issue-title">
                T-{issue.task_number}: {issue.task_title}
              </div>
              <div className="ws-issue-reason">{issue.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

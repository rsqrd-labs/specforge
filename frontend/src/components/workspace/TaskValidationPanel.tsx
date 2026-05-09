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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span className="ws-panel-title" style={{ marginBottom: 0 }}>Task Validation</span>
        {evalResult && (
          <span style={{ fontSize: 11, fontWeight: 600, color: issues.length === 0 ? "#16a34a" : "#dc2626" }}>
            {issues.length === 0 ? "All clear" : `${issues.length} flagged`}
          </span>
        )}
      </div>

      {!evalResult && (
        <p style={{ fontSize: 12, color: "var(--color-on-surface-variant)" }}>Evaluating…</p>
      )}

      {evalResult && issues.length === 0 && (
        <p className="ws-panel-ok">✓ Every task references a test.</p>
      )}

      {issues.length > 0 && (
        <ul style={{ display: "flex", flexDirection: "column", gap: 6 }}>
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

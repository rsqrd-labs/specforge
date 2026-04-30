import type { EvalResult, Stage } from "../../types/stage"

interface TaskValidationPanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
}

export function TaskValidationPanel({
  stage,
  evalResult,
}: TaskValidationPanelProps) {
  if (stage.type !== "tasks") {
    return null
  }

  const issues = evalResult?.tasks_without_ref ?? []

  return (
    <section className="border-t border-outline-variant bg-surface px-4 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-on-surface">
          Task Validation
        </h2>
        <span className="text-xs font-medium text-on-surface-variant">
          {evalResult ? `${issues.length} flagged` : "Evaluating..."}
        </span>
      </div>

      {evalResult && issues.length === 0 && (
        <p className="text-sm text-on-surface-variant">
          Every task references a test.
        </p>
      )}

      {issues.length > 0 && (
        <ul className="space-y-2">
          {issues.map((issue) => (
            <li
              key={`${issue.task_number}-${issue.task_title}`}
              className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
            >
              <div className="font-medium">
                T-{issue.task_number}: {issue.task_title}
              </div>
              <div className="mt-1 text-amber-800">{issue.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

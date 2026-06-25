import type { EvalResult, Stage, TaskReferenceIssue } from "../../types/stage"

interface TaskValidationPanelProps {
  stage: Stage
  evalResult: EvalResult | null | undefined
  onNavigateToHarness?: () => void
  disabled?: boolean
  disabledReason?: string
}

function isGenuineGap(issue: TaskReferenceIssue): boolean {
  return !issue.gap_type || issue.gap_type === "GENUINE_GAP"
}

function isDeferredCoverage(issue: TaskReferenceIssue): boolean {
  return issue.gap_type === "DEFERRED_COVERAGE"
}

export function TaskValidationPanel({
  stage,
  evalResult,
  onNavigateToHarness,
  disabled = false,
  disabledReason,
}: TaskValidationPanelProps) {
  if (stage.type !== "tasks") return null

  const allIssues = evalResult?.tasks_without_ref ?? []
  const genuineGaps = allIssues.filter(isGenuineGap)
  const deferredGaps = allIssues.filter(isDeferredCoverage)
  const disabledReasonId = `${stage.id}-task-validation-disabled-reason`

  if (!evalResult) {
    return (
      <div className="ws-panel-section ws-coverage-card ws-coverage-card--loading">
        <div className="ws-panel-title">Coverage Gaps</div>
        <p className="ws-panel-muted">Checking task traceability…</p>
      </div>
    )
  }

  if (genuineGaps.length === 0 && deferredGaps.length === 0) return null

  return (
    <>
      {genuineGaps.length > 0 && (
        <div className="ws-panel-section ws-coverage-card ws-coverage-card--gap">
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

                <div className="ws-issue-reason">
                  {issue.remediation ?? issue.reason}
                </div>

                {issue.code_stub && (
                  <pre className="ws-issue-code-stub">{issue.code_stub}</pre>
                )}

                {onNavigateToHarness && (
                  <button
                    type="button"
                    className="ws-issue-action"
                    onClick={onNavigateToHarness}
                    disabled={disabled}
                    title={disabled ? disabledReason : undefined}
                    aria-describedby={
                      disabled && disabledReason ? disabledReasonId : undefined
                    }
                    aria-label="Open HARNESS"
                  >
                    Open
                  </button>
                )}
              </li>
            ))}
          </ul>
          {disabled && disabledReason ? (
            <p id={disabledReasonId} className="workspace-lock-inline-note">
              {disabledReason}
            </p>
          ) : null}
        </div>
      )}

      {deferredGaps.length > 0 && (
        <div className="ws-panel-section ws-coverage-card ws-coverage-card--deferred">
          <div className="ws-panel-section-header">
            <div>
              <div className="ws-panel-title">Deferred Coverage</div>
              <p>
                {deferredGaps.length === 1
                  ? "1 task relies on a test category the harness deferred under its budget. This is non-blocking."
                  : `${deferredGaps.length} tasks rely on test categories the harness deferred under its budget. These are non-blocking.`}
              </p>
            </div>
            <span className="ws-panel-chip">
              {deferredGaps.length} deferred
            </span>
          </div>

          <ul className="ws-issue-list">
            {deferredGaps.map((issue) => (
              <li
                key={`${issue.task_number}-${issue.task_title}`}
                className="ws-issue-item"
              >
                <div className="ws-issue-title">
                  T-{issue.task_number}: {issue.task_title}
                </div>

                {issue.harness_file && (
                  <div className="ws-issue-file-tag">{issue.harness_file}</div>
                )}

                <div className="ws-issue-reason">
                  {issue.remediation ?? issue.reason}
                </div>

                {onNavigateToHarness && (
                  <button
                    type="button"
                    className="ws-issue-action"
                    onClick={onNavigateToHarness}
                    disabled={disabled}
                    title={disabled ? disabledReason : undefined}
                    aria-describedby={
                      disabled && disabledReason ? disabledReasonId : undefined
                    }
                    aria-label="Open HARNESS"
                  >
                    Open
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

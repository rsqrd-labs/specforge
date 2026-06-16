import type { ReactNode } from "react"
import type { Stage } from "../../types/stage"

interface ProblemStatementPanelProps {
  stage: Stage
  problemStatement: string
  isDirty?: boolean
  readOnly?: boolean
  readOnlyReason?: string
  onChange?: (value: string) => void
  onBlur?: () => void
  /** Optional controls rendered in the panel footer (e.g. web-research opt-in). */
  footer?: ReactNode
}

export function ProblemStatementPanel({
  stage,
  problemStatement,
  isDirty = false,
  readOnly = false,
  readOnlyReason,
  onChange,
  onBlur,
  footer,
}: ProblemStatementPanelProps) {
  if (stage.type !== "spec") return null

  const words = problemStatement.trim()
    ? problemStatement.trim().split(/\s+/).length
    : 0
  const characters = problemStatement.length
  const status = stage.status.replace("_", " ")
  const readOnlyReasonId = `${stage.id}-problem-readonly-reason`

  return (
    <div className="workspace-document-card problem-editor-pane">
      <div className="workspace-pane-header">
        <div>
          <div className="ws-panel-title">Source Brief</div>
          <h2 className="workspace-pane-title">Problem Statement</h2>
        </div>
        <span className={`document-save-state ${isDirty ? "dirty" : "saved"}`}>
          {isDirty ? "Unsaved" : "Saved"}
        </span>
      </div>
      <div className="problem-editor-body">
        {readOnly && readOnlyReason ? (
          <div id={readOnlyReasonId} className="problem-editor-readonly-note">
            {readOnlyReason}
          </div>
        ) : null}
        <textarea
          value={problemStatement}
          readOnly={readOnly}
          maxLength={10000}
          onChange={(event) => {
            if (!readOnly) onChange?.(event.target.value)
          }}
          onBlur={onBlur}
          aria-describedby={readOnly && readOnlyReason ? readOnlyReasonId : undefined}
          className="problem-editor-textarea"
        />
      </div>
      <div className="source-metric-strip">
        <div>
          <span>Words</span>
          <strong>{words}</strong>
        </div>
        <div>
          <span>Chars</span>
          <strong>{characters}</strong>
        </div>
        <div>
          <span>Status</span>
          <strong>{status}</strong>
        </div>
      </div>
      {footer ? <div className="source-brief-footer">{footer}</div> : null}
    </div>
  )
}

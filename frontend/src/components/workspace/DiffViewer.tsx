interface DiffViewerProps {
  diff: string
  original: string
  proposed: string
  onAccept: (proposed: string) => void
  onReject: () => void
  disabled?: boolean
  disabledReason?: string
}

interface DiffLine {
  type: "add" | "remove" | "context" | "header"
  content: string
}

function parseDiff(diff: string): DiffLine[] {
  return diff.split("\n").map((line) => {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) {
      return { type: "header", content: line }
    }
    if (line.startsWith("+")) return { type: "add", content: line.slice(1) }
    if (line.startsWith("-")) return { type: "remove", content: line.slice(1) }
    return { type: "context", content: line.startsWith(" ") ? line.slice(1) : line }
  })
}

export function DiffViewer({
  diff,
  proposed,
  onAccept,
  onReject,
  disabled = false,
  disabledReason,
}: DiffViewerProps) {
  const lines = parseDiff(diff)
  const disabledReasonId = disabledReason ? "diff-actions-disabled-reason" : undefined

  return (
    <div className="diff-viewer">
      <div className="diff-viewer-header">
        <div>
          <div className="ws-panel-title">Proposed changes</div>
          <p>Review the patch before applying it.</p>
        </div>
        <span>{lines.length} lines</span>
      </div>

      <div className="diff-content">
        {lines.map((line, i) => (
          <div key={i} className={`diff-line ${line.type}`}>
            {line.type === "add" && <span className="diff-gutter">+</span>}
            {line.type === "remove" && <span className="diff-gutter">−</span>}
            {line.type !== "add" && line.type !== "remove" && (
              <span className="diff-gutter"> </span>
            )}
            {line.content}
          </div>
        ))}
      </div>

      <div className="diff-actions">
        <p className="diff-credit-disclosure">
          Rejecting keeps your document unchanged; the 3-credit refinement charge
          is not refunded.
        </p>
        {disabled && disabledReason ? (
          <p id={disabledReasonId} className="workspace-lock-inline-note">
            {disabledReason}
          </p>
        ) : null}
        <button
          onClick={onReject}
          className="gen-btn-secondary"
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
          aria-describedby={disabled ? disabledReasonId : undefined}
        >
          Reject
        </button>
        <button
          onClick={() => onAccept(proposed)}
          className="gen-btn-primary"
          aria-label="Accept changes"
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
          aria-describedby={disabled ? disabledReasonId : undefined}
        >
          Accept
        </button>
      </div>
    </div>
  )
}

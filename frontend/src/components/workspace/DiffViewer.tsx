interface DiffViewerProps {
  diff: string
  original: string
  proposed: string
  onAccept: (proposed: string) => void
  onReject: () => void
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

export function DiffViewer({ diff, proposed, onAccept, onReject }: DiffViewerProps) {
  const lines = parseDiff(diff)

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
        <button onClick={onReject} className="gen-btn-secondary">
          Reject
        </button>
        <button onClick={() => onAccept(proposed)} className="gen-btn-primary">
          Accept changes
        </button>
      </div>
    </div>
  )
}

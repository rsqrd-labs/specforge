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

export function DiffViewer({
  diff,
  proposed,
  onAccept,
  onReject,
}: DiffViewerProps) {
  const lines = parseDiff(diff)

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto font-mono text-sm bg-surface-container-lowest rounded-lg p-3">
        {lines.map((line, i) => {
          const bg =
            line.type === "add"
              ? "bg-green-50 text-green-800"
              : line.type === "remove"
                ? "bg-red-50 text-red-800"
                : line.type === "header"
                  ? "text-on-surface-variant text-xs"
                  : "text-on-surface"

          return (
            <div key={i} className={`px-2 py-0.5 whitespace-pre-wrap ${bg}`}>
              {line.type === "add" && (
                <span className="text-green-600 select-none mr-1">+</span>
              )}
              {line.type === "remove" && (
                <span className="text-red-600 select-none mr-1">-</span>
              )}
              {line.content}
            </div>
          )
        })}
      </div>

      <div className="flex justify-end gap-3 pt-3">
        <button
          onClick={onReject}
          className="px-4 py-2 text-sm text-on-surface-variant hover:text-on-surface border border-outline-variant rounded-lg"
        >
          Reject
        </button>
        <button
          onClick={() => onAccept(proposed)}
          className="px-4 py-2 text-sm font-medium bg-primary text-on-primary rounded-lg hover:opacity-90"
        >
          Accept Changes
        </button>
      </div>
    </div>
  )
}

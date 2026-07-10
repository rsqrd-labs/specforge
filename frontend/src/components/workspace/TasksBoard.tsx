import { useMemo, useRef, useState } from "react"
import { MarkdownRenderer } from "./MarkdownRenderer"
import { TaskCard } from "./TaskCard"
import { extractTaskFrontMatter, parseTaskBlocks, type TaskBlock } from "../../utils/tasksParser"

interface TasksBoardProps {
  content: string
}

interface TaskEntry {
  task: TaskBlock
  /** `task.id` unless the document repeats an ID (seen on regenerated/
   *  gap-patched documents in practice) — then occurrence-suffixed so React
   *  keys, DOM anchors, and expand/collapse state can never collide. */
  anchorId: string
}

/**
 * Renders TASKS.md as collapsible per-task cards with clickable dependency
 * links, instead of one continuous markdown scroll (2026-07 design review
 * remediation: "Tasks throws away its own structure"). Falls back to the
 * plain MarkdownRenderer, unchanged, whenever the content doesn't contain the
 * `### T-NNN:` heading shape the parser expects — an older or malformed
 * document still renders in full, just without the card affordance.
 */
export function TasksBoard({ content }: TasksBoardProps) {
  const tasks = useMemo(() => parseTaskBlocks(content), [content])
  const frontMatter = useMemo(() => extractTaskFrontMatter(content), [content])
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [highlighted, setHighlighted] = useState<string | null>(null)
  const highlightTimeoutRef = useRef<number | null>(null)

  // A generated document can legitimately repeat a task ID (observed after a
  // gap-patch regenerate appends a later block reusing an earlier number) —
  // disambiguate so every card gets its own React key, DOM anchor, and
  // independent expand/collapse state instead of colliding on the bare ID.
  const entries = useMemo<TaskEntry[]>(() => {
    const seen = new Map<string, number>()
    return tasks.map((task) => {
      const count = seen.get(task.id) ?? 0
      seen.set(task.id, count + 1)
      return { task, anchorId: count === 0 ? task.id : `${task.id}~${count}` }
    })
  }, [tasks])

  const knownTaskIds = useMemo(() => new Set(tasks.map((t) => t.id)), [tasks])
  // Dependency links jump to the first occurrence of a given task ID.
  const firstAnchorById = useMemo(() => {
    const map = new Map<string, string>()
    for (const entry of entries) {
      if (!map.has(entry.task.id)) map.set(entry.task.id, entry.anchorId)
    }
    return map
  }, [entries])

  if (tasks.length === 0) {
    return (
      <div className="document-markdown-scroll">
        <MarkdownRenderer content={content} />
      </div>
    )
  }

  const toggle = (anchorId: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(anchorId)) next.delete(anchorId)
      else next.add(anchorId)
      return next
    })
  }

  const navigateToTask = (id: string) => {
    const anchorId = firstAnchorById.get(id)
    if (!anchorId) return
    setExpanded((current) => new Set(current).add(anchorId))
    // Wait a frame for the expanded body to mount before measuring/scrolling.
    window.requestAnimationFrame(() => {
      document.getElementById(`task-${anchorId}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
    })
    if (highlightTimeoutRef.current) window.clearTimeout(highlightTimeoutRef.current)
    setHighlighted(anchorId)
    highlightTimeoutRef.current = window.setTimeout(() => setHighlighted(null), 2200)
  }

  const allExpanded = entries.every((e) => expanded.has(e.anchorId))

  return (
    <div className="document-markdown-scroll tasks-board">
      {frontMatter && (
        <div className="tasks-board-frontmatter">
          <MarkdownRenderer content={frontMatter} />
        </div>
      )}

      <div className="tasks-board-toolbar">
        <span className="tasks-board-count">{tasks.length} tasks</span>
        <button
          type="button"
          className="tasks-board-expand-all"
          onClick={() =>
            setExpanded(allExpanded ? new Set() : new Set(entries.map((e) => e.anchorId)))
          }
        >
          {allExpanded ? "Collapse all" : "Expand all"}
        </button>
      </div>

      <div className="tasks-board-list">
        {entries.map(({ task, anchorId }) => (
          <TaskCard
            key={anchorId}
            task={task}
            anchorId={anchorId}
            expanded={expanded.has(anchorId)}
            onToggle={toggle}
            onNavigateToTask={navigateToTask}
            highlighted={highlighted === anchorId}
            knownTaskIds={knownTaskIds}
          />
        ))}
      </div>
    </div>
  )
}

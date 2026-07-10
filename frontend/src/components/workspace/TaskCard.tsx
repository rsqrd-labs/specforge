import { MarkdownRenderer } from "./MarkdownRenderer"
import type { TaskBlock } from "../../utils/tasksParser"

interface TaskCardProps {
  task: TaskBlock
  /** Unique per rendered card — `task.id` unless the document repeats an ID,
   *  in which case the board suffixes it. Used for the DOM anchor and as the
   *  toggle/highlight identity so duplicate IDs never collide. */
  anchorId: string
  expanded: boolean
  onToggle: (anchorId: string) => void
  onNavigateToTask: (id: string) => void
  /** True for the card the user was just scrolled to via a dependency link —
   *  drives a brief highlight so they can find it among 20+ siblings. */
  highlighted: boolean
  /** Whether each dependency ID actually exists in this document — an
   *  unresolvable reference still renders (never silently drops data) but
   *  isn't clickable. */
  knownTaskIds: ReadonlySet<string>
}

const PRIORITY_CLASS: Record<string, string> = {
  MUST: "task-card-priority-must",
  SHOULD: "task-card-priority-should",
  COULD: "task-card-priority-could",
}

export function TaskCard({
  task,
  anchorId,
  expanded,
  onToggle,
  onNavigateToTask,
  highlighted,
  knownTaskIds,
}: TaskCardProps) {
  const priorityClass = task.priority ? PRIORITY_CLASS[task.priority.toUpperCase()] : undefined

  return (
    <article
      id={`task-${anchorId}`}
      className={`task-card${expanded ? " is-expanded" : ""}${highlighted ? " is-highlighted" : ""}`}
    >
      <button
        type="button"
        className="task-card-summary"
        onClick={() => onToggle(anchorId)}
        aria-expanded={expanded}
      >
        <svg
          className="task-card-chevron"
          viewBox="0 0 10 6"
          fill="none"
          aria-hidden="true"
        >
          <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="task-card-id">{task.id}</span>
        {task.priority && (
          <span className={`task-card-badge ${priorityClass ?? ""}`}>{task.priority}</span>
        )}
        {task.estimate && <span className="task-card-badge task-card-badge-muted">{task.estimate}</span>}
        <span className="task-card-title">{task.title}</span>
      </button>

      {expanded && (
        <div className="task-card-body">
          <div className="task-card-meta-grid">
            {task.phase && (
              <div>
                <span>Phase</span>
                <strong>{task.phase}</strong>
              </div>
            )}
            {task.owner && (
              <div>
                <span>Owner</span>
                <strong>{task.owner}</strong>
              </div>
            )}
            {task.risk && (
              <div>
                <span>Risk</span>
                <strong>{task.risk}</strong>
              </div>
            )}
            {task.estimatedSize && (
              <div>
                <span>Size</span>
                <strong>{task.estimatedSize}</strong>
              </div>
            )}
          </div>

          {task.dependencies.length > 0 && (
            <div className="task-card-deps">
              <span className="task-card-deps-label">Depends on</span>
              {task.dependencies.map((depId) => (
                <button
                  key={depId}
                  type="button"
                  className="task-card-dep-chip"
                  disabled={!knownTaskIds.has(depId)}
                  title={knownTaskIds.has(depId) ? `Jump to ${depId}` : `${depId} is not in this document`}
                  onClick={() => onNavigateToTask(depId)}
                >
                  {depId}
                </button>
              ))}
            </div>
          )}

          {task.description && (
            <section className="task-card-section">
              <h4>Description</h4>
              <MarkdownRenderer content={task.description} />
            </section>
          )}
          {task.steps && (
            <section className="task-card-section">
              <h4>Steps</h4>
              <MarkdownRenderer content={task.steps} />
            </section>
          )}
          {task.acceptanceCriteria && (
            <section className="task-card-section">
              <h4>Acceptance Criteria</h4>
              <MarkdownRenderer content={task.acceptanceCriteria} />
            </section>
          )}
          {task.inputs && (
            <section className="task-card-section">
              <h4>Inputs</h4>
              <MarkdownRenderer content={task.inputs} />
            </section>
          )}
          {task.outputs && (
            <section className="task-card-section">
              <h4>Outputs</h4>
              <MarkdownRenderer content={task.outputs} />
            </section>
          )}
          {task.rollback && (
            <section className="task-card-section">
              <h4>Rollback / Recovery</h4>
              <MarkdownRenderer content={task.rollback} />
            </section>
          )}
          {(task.specRefs || task.planRefs || task.harnessRefs) && (
            <section className="task-card-section task-card-refs">
              <h4>Traceability</h4>
              {task.specRefs && <p><span>Spec</span> {task.specRefs}</p>}
              {task.planRefs && <p><span>Plan</span> {task.planRefs}</p>}
              {task.harnessRefs && <p><span>Harness</span> {task.harnessRefs}</p>}
            </section>
          )}
        </div>
      )}
    </article>
  )
}

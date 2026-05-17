import type { Stage } from "../../types/stage"

interface GenerateBarProps {
  stage: Stage
  onGenerate: () => void
  onRegenerate: () => void
  onRefine: () => void
  onFinalise: () => void
  onUnlock: () => void
}

export function GenerateBar({
  stage,
  onGenerate,
  onRegenerate,
  onRefine,
  onFinalise,
  onUnlock,
}: GenerateBarProps) {
  if (stage.status === "locked") return null

  const generateLabel =
    stage.type === "spec" || stage.type === "plan"
      ? "Generate deep architecture pass"
      : "Generate fast draft"

  if (stage.status === "in_progress") {
    return (
      <div className="gen-btn-streaming">
        <div className="loading-ring" />
        <span>Generating…</span>
      </div>
    )
  }

  return (
    <div className="workspace-action-row">
      {(stage.status === "draft" || stage.status === "stale") && !stage.content && (
        <button type="button" onClick={onGenerate} className="gen-btn-primary">
          {generateLabel}
        </button>
      )}

      {stage.status === "finalised" ? (
        <button type="button" onClick={onUnlock} className="gen-btn-secondary">
          Unlock stage
        </button>
      ) : (stage.status === "stale" ||
        (stage.status === "draft" && stage.content)) ? (
        <button
          type="button"
          onClick={onRegenerate}
          className="gen-btn-secondary gen-btn-deliberate"
        >
          Full stage regenerate
        </button>
      ) : null}

      {stage.content && stage.status !== "finalised" && (
        <button
          type="button"
          onClick={onRefine}
          className="gen-btn-secondary"
          aria-label="Focused patch refine"
        >
          Focused patch
        </button>
      )}

      {(stage.status === "draft" || stage.status === "stale") && stage.content && (
        <button type="button" onClick={onFinalise} className="gen-btn-primary">
          Final quality pass
        </button>
      )}
    </div>
  )
}

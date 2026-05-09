import type { Stage } from "../../types/stage"

interface GenerateBarProps {
  stage: Stage
  onGenerate: () => void
  onRegenerate: () => void
  onRefine: () => void
  onFinalise: () => void
}

export function GenerateBar({
  stage,
  onGenerate,
  onRegenerate,
  onRefine,
  onFinalise,
}: GenerateBarProps) {
  if (stage.status === "locked") return null

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
        <button onClick={onGenerate} className="gen-btn-primary">
          Generate
        </button>
      )}

      {(stage.status === "finalised" ||
        stage.status === "stale" ||
        (stage.status === "draft" && stage.content)) && (
        <button onClick={onRegenerate} className="gen-btn-secondary">
          Regenerate
        </button>
      )}

      {stage.content && (
        <button onClick={onRefine} className="gen-btn-secondary">
          Refine
        </button>
      )}

      {(stage.status === "draft" || stage.status === "stale") && stage.content && (
        <button onClick={onFinalise} className="gen-btn-primary">
          Finalise
        </button>
      )}
    </div>
  )
}

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
  const btnBase =
    "px-3 py-1.5 text-sm font-medium rounded-lg transition-opacity"
  const primary = `${btnBase} bg-primary text-on-primary hover:opacity-90`
  const secondary = `${btnBase} border border-outline-variant text-on-surface hover:bg-surface-container`

  if (stage.status === "locked") return null

  if (stage.status === "in_progress") {
    return (
      <div className="flex items-center gap-2 text-sm text-on-surface-variant">
        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary" />
        <span>Generating…</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      {(stage.status === "draft" || stage.status === "stale") && !stage.content && (
        <button onClick={onGenerate} className={primary}>
          Generate
        </button>
      )}

      {(stage.status === "finalised" ||
        stage.status === "stale" ||
        (stage.status === "draft" && stage.content)) && (
        <button onClick={onRegenerate} className={secondary}>
          Regenerate
        </button>
      )}

      {stage.content && (
        <button onClick={onRefine} className={secondary}>
          Refine
        </button>
      )}

      {(stage.status === "draft" || stage.status === "stale") &&
        stage.content && (
          <button onClick={onFinalise} className={primary}>
            Finalise
          </button>
        )}
    </div>
  )
}

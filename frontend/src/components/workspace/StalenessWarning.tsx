import type { Stage } from "../../types/stage"

interface StalenessWarningProps {
  stage: Stage
  upstreamStageType: string
  onRegenerate: () => void
  onDismiss: () => void
}

export function StalenessWarning({
  stage,
  upstreamStageType,
  onRegenerate,
  onDismiss,
}: StalenessWarningProps) {
  if (stage.status !== "stale") {
    return null
  }

  return (
    <div className="flex items-center justify-between gap-4 border-b border-primary-container/40 bg-primary-container/10 px-5 py-3 text-sm text-on-primary-container">
      <p>
        This stage was generated from a previous version of {upstreamStageType}.
        Regenerate or keep as-is?
      </p>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onDismiss}
          className="font-medium text-on-primary-container hover:text-primary"
        >
          Keep as-is
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="rounded-lg bg-primary px-3 py-1.5 font-medium text-on-primary hover:opacity-90"
        >
          Regenerate
        </button>
      </div>
    </div>
  )
}

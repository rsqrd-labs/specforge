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
    <div className="flex items-center justify-between gap-4 border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p>
        This stage was generated from a previous version of {upstreamStageType}.
        Regenerate or keep as-is?
      </p>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onDismiss}
          className="px-3 py-1.5 font-medium text-amber-900 hover:text-amber-700"
        >
          Keep as-is
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="rounded-lg bg-amber-600 px-3 py-1.5 font-medium text-white hover:bg-amber-700"
        >
          Regenerate
        </button>
      </div>
    </div>
  )
}

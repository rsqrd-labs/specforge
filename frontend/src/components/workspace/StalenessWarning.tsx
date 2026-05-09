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
  if (stage.status !== "stale") return null

  return (
    <div className="ws-banner ws-warning">
      <span>
        This stage was generated from an older version of {upstreamStageType}.
      </span>
      <div className="flex shrink-0 items-center gap-3">
        <button
          type="button"
          onClick={onDismiss}
          className="ws-banner-link"
        >
          Keep as-is
        </button>
        <button type="button" onClick={onRegenerate} className="gen-btn-primary gen-btn-compact">
          Regenerate
        </button>
      </div>
    </div>
  )
}

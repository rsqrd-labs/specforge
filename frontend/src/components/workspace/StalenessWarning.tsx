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
          className="text-xs font-medium opacity-70 hover:opacity-100"
        >
          Keep as-is
        </button>
        <button type="button" onClick={onRegenerate} className="gen-btn-primary"
          style={{ padding: "5px 14px", fontSize: 12 }}>
          ↺ Regenerate
        </button>
      </div>
    </div>
  )
}

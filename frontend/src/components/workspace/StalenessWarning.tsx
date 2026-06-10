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
    <div className="staleness-strip">
      <div className="staleness-icon-wrap" aria-hidden="true">
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="8" cy="8" r="6.5" />
          <path d="M8 5v3.5l2 1.5" />
        </svg>
      </div>

      <div className="staleness-body">
        <span className="staleness-label">Out of sync</span>
        <p className="staleness-detail">
          Generated from an older version of{" "}
          <strong>{upstreamStageType}</strong> — upstream changes may not be
          reflected here.
        </p>
      </div>

      <div className="staleness-actions">
        <button type="button" onClick={onDismiss} className="staleness-dismiss">
          Keep
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="gen-btn-primary gen-btn-compact"
        >
          Regenerate
        </button>
      </div>
    </div>
  )
}

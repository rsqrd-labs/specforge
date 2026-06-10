import type { Stage } from "../../types/stage"

interface StalenessWarningProps {
  stage: Stage
  upstreamStageType: string
  onRegenerate: () => void
  onDismiss: () => void
  disabled?: boolean
  disabledReason?: string
}

export function StalenessWarning({
  stage,
  upstreamStageType,
  onRegenerate,
  onDismiss,
  disabled = false,
  disabledReason,
}: StalenessWarningProps) {
  if (stage.status !== "stale") return null
  const disabledReasonId = `${stage.id}-staleness-disabled-reason`

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
        {disabled && disabledReason ? (
          <span id={disabledReasonId} className="workspace-lock-inline-note">
            {disabledReason}
          </span>
        ) : null}
        <button
          type="button"
          onClick={onDismiss}
          className="staleness-dismiss"
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
          aria-describedby={disabled ? disabledReasonId : undefined}
        >
          Keep
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="gen-btn-primary gen-btn-compact"
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
          aria-describedby={disabled ? disabledReasonId : undefined}
        >
          Regenerate
        </button>
      </div>
    </div>
  )
}

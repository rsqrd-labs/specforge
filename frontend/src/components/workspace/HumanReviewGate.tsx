import { useRef } from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"

interface HumanReviewGateProps {
  fromStageType: string
  toStageType: string
  onProceed: () => void
  onClose: () => void
  disabled?: boolean
  disabledReason?: string
}

export function HumanReviewGate({
  fromStageType,
  toStageType,
  onProceed,
  onClose,
  disabled = false,
  disabledReason,
}: HumanReviewGateProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onClose)
  const disabledReasonId = disabledReason ? "review-gate-disabled-reason" : undefined

  return (
    <div
      className="create-modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-gate-title"
        className="create-modal workspace-review-modal"
      >
        <div className="create-modal-header">
          <h2 id="review-gate-title" className="create-modal-title">
            Review before generating
          </h2>
          <button onClick={onClose} className="create-modal-close" aria-label="Close">✕</button>
        </div>

        <div className="create-modal-body">
          <div className="workspace-review-card">
            You are about to generate <strong>{toStageType}</strong> from{" "}
            <em>{fromStageType}</em>. Take a moment to review the
            source stage before continuing — this will consume credits.
          </div>
          {disabled && disabledReason ? (
            <p id={disabledReasonId} className="workspace-lock-inline-note">
              {disabledReason}
            </p>
          ) : null}

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="modal-cancel">
              Back
            </button>
            <button
              type="button"
              onClick={onProceed}
              className="modal-submit"
              disabled={disabled}
              title={disabled ? disabledReason : undefined}
              aria-describedby={disabled ? disabledReasonId : undefined}
            >
              Generate
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

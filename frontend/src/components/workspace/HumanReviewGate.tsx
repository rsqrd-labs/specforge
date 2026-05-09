import { useRef } from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"

interface HumanReviewGateProps {
  fromStageType: string
  toStageType: string
  onProceed: () => void
  onClose: () => void
}

export function HumanReviewGate({
  fromStageType,
  toStageType,
  onProceed,
  onClose,
}: HumanReviewGateProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onClose)

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

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="modal-cancel">
              Go back
            </button>
            <button type="button" onClick={onProceed} className="modal-submit">
              Proceed
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

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
        className="create-modal"
        style={{ maxWidth: 440 }}
      >
        <div className="create-modal-header">
          <h2 id="review-gate-title" className="create-modal-title">
            Review before generating
          </h2>
          <button onClick={onClose} className="create-modal-close" aria-label="Close">✕</button>
        </div>

        <div className="create-modal-body">
          <div
            style={{
              padding: "14px 16px",
              borderRadius: 12,
              border: "1px solid rgba(143,78,0,0.12)",
              background: "rgba(143,78,0,0.05)",
              fontSize: 13,
              lineHeight: 1.6,
              color: "var(--color-on-surface-variant)",
            }}
          >
            You are about to generate <strong style={{ color: "var(--color-primary)" }}>{toStageType}</strong> from{" "}
            <strong style={{ color: "var(--color-on-surface)" }}>{fromStageType}</strong>. Take a moment to review the
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

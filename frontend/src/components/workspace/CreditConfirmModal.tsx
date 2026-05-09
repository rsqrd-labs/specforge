import { useRef } from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"

interface CreditConfirmModalProps {
  action: "generate" | "regenerate" | "refine"
  creditCost?: number
  currentBalance?: number
  cost?: number
  balance?: number
  open?: boolean
  onConfirm: () => void
  onCancel: () => void
}

const CREDIT_COSTS = {
  generate: 10,
  regenerate: 10,
  refine: 3,
}

const ACTION_LABELS: Record<string, string> = {
  generate: "Generate",
  regenerate: "Regenerate",
  refine: "Refine",
}

export function CreditConfirmModal({
  action,
  creditCost,
  currentBalance,
  cost,
  balance,
  open,
  onConfirm,
  onCancel,
}: CreditConfirmModalProps) {
  if (open === false) return null

  const resolvedCost = creditCost ?? cost ?? CREDIT_COSTS[action]
  const resolvedBalance = currentBalance ?? balance ?? 0
  const remaining = resolvedBalance - resolvedCost
  const isInsufficient = resolvedBalance < resolvedCost
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onCancel)

  return (
    <div
      className="create-modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onCancel()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="credit-modal-title"
        className="create-modal"
        style={{ maxWidth: 400 }}
      >
        <div className="create-modal-header">
          <h2 id="credit-modal-title" className="create-modal-title">
            {ACTION_LABELS[action] ?? action}
          </h2>
          <button onClick={onCancel} className="create-modal-close" aria-label="Close">✕</button>
        </div>

        <div className="create-modal-body">
          <div
            style={{
              padding: "14px 16px",
              borderRadius: 12,
              border: "1px solid rgba(143,78,0,0.12)",
              background: "rgba(143,78,0,0.05)",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
              <span style={{ color: "var(--color-on-surface-variant)" }}>Cost</span>
              <span style={{ fontWeight: 700, color: "var(--color-primary)" }}>
                {resolvedCost} credits
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
              <span style={{ color: "var(--color-on-surface-variant)" }}>Balance</span>
              <span style={{ fontWeight: 600 }}>{resolvedBalance} credits</span>
            </div>
            <div
              style={{
                borderTop: "1px solid rgba(143,78,0,0.10)",
                paddingTop: 8,
                display: "flex",
                justifyContent: "space-between",
                fontSize: 13,
              }}
            >
              <span style={{ color: "var(--color-on-surface-variant)" }}>After</span>
              <span
                style={{
                  fontWeight: 700,
                  color: isInsufficient ? "#dc2626" : "var(--color-on-surface)",
                }}
              >
                {remaining} credits
              </span>
            </div>
          </div>

          {isInsufficient && (
            <p className="modal-error" style={{ marginTop: 0 }}>
              Insufficient credits to proceed.
            </p>
          )}

          <div className="modal-footer">
            <button type="button" onClick={onCancel} className="modal-cancel">
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isInsufficient}
              className="modal-submit"
            >
              Confirm
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export { CREDIT_COSTS }

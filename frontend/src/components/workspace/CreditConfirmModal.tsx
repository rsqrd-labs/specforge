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
  generate: "Fast draft",
  regenerate: "Full stage regenerate",
  refine: "Focused patch",
}

const ACTION_COPY: Record<string, string> = {
  generate:
    "Create the next ASDD artifact with the right level of architectural depth.",
  regenerate:
    "Replace this full stage with a fresh pass. Best for stale or oversized changes.",
  refine:
    "Preview a focused patch for the selected text before accepting changes.",
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
        className="create-modal workspace-credit-modal"
      >
        <div className="create-modal-header">
          <h2 id="credit-modal-title" className="create-modal-title">
            {ACTION_LABELS[action] ?? action}
          </h2>
          <button onClick={onCancel} className="create-modal-close" aria-label="Close">✕</button>
        </div>

        <div className="create-modal-body">
          <p className="workspace-credit-value-copy">
            {ACTION_COPY[action] ?? "Review this action before spending credits."}
          </p>
          <div className="workspace-credit-summary">
            <div>
              <span>Cost</span>
              <strong>
                <span>{resolvedCost}</span> credits
              </strong>
              <span className="sr-only">{resolvedCost} credits</span>
            </div>
            <div>
              <span>Balance</span>
              <strong>
                <span>{resolvedBalance}</span> credits
              </strong>
              <span className="sr-only">{resolvedBalance} credits</span>
            </div>
            <div className="workspace-credit-after">
              <span>After</span>
              <strong className={isInsufficient ? "danger" : ""}>
                <span>{remaining}</span> remaining
              </strong>
              <span className="sr-only">{remaining} remaining</span>
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

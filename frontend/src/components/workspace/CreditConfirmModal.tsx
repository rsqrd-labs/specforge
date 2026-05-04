import { useRef } from "react"
import { useFocusTrap } from "../../hooks/useFocusTrap"

interface CreditConfirmModalProps {
  action: "generate" | "regenerate" | "refine"
  creditCost: number
  currentBalance: number
  onConfirm: () => void
  onCancel: () => void
}

const CREDIT_COSTS = {
  generate: 10,
  regenerate: 10,
  refine: 3,
}

export function CreditConfirmModal({
  action,
  creditCost,
  currentBalance,
  onConfirm,
  onCancel,
}: CreditConfirmModalProps) {
  const isInsufficient = currentBalance < creditCost
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onCancel)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f172a]/60 p-4 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onCancel()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="credit-modal-title"
        className="w-full max-w-sm rounded-xl border border-outline-variant bg-surface-container-lowest/90 p-6 shadow-[0_40px_100px_rgba(47,49,49,0.22)] backdrop-blur-xl"
      >
        <div className="mb-1 text-xs font-semibold uppercase tracking-widest text-primary">
          Credit usage
        </div>
        <h2
          id="credit-modal-title"
          className="mb-2 text-lg font-semibold capitalize text-on-surface"
        >
          {action}
        </h2>
        <p className="mb-6 text-sm leading-6 text-on-surface-variant">
          This will use{" "}
          <span className="font-semibold text-on-surface">{creditCost}</span>{" "}
          credits. You have{" "}
          <span
            className={`font-semibold ${
              isInsufficient ? "text-error" : "text-on-surface"
            }`}
          >
            {currentBalance}
          </span>{" "}
          remaining.
          {isInsufficient && (
            <span className="mt-2 block text-error">
              Insufficient credits to proceed.
            </span>
          )}
        </p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-outline-variant px-4 py-2 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isInsufficient}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-[0_4px_16px_rgba(143,78,0,0.22)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}

export { CREDIT_COSTS }

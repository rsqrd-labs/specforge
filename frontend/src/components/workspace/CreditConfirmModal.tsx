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
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => e.target === e.currentTarget && onCancel()}
    >
      <div className="bg-surface rounded-xl w-full max-w-sm shadow-xl p-6">
        <h2 className="text-lg font-semibold text-on-surface mb-2 capitalize">
          {action}
        </h2>
        <p className="text-sm text-on-surface-variant mb-6">
          This will use{" "}
          <span className="font-semibold text-on-surface">{creditCost}</span>{" "}
          credits. You have{" "}
          <span className="font-semibold text-on-surface">{currentBalance}</span>{" "}
          remaining. Proceed?
        </p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-on-surface-variant hover:text-on-surface"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm font-medium bg-primary text-on-primary rounded-lg hover:opacity-90"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}

export { CREDIT_COSTS }

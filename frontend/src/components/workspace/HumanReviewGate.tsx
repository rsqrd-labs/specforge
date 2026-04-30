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
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="w-full max-w-md rounded-xl bg-surface p-6 shadow-xl">
        <h2 className="mb-2 text-lg font-semibold text-on-surface">
          Review before generating
        </h2>
        <p className="mb-6 text-sm leading-6 text-on-surface-variant">
          You are about to generate {toStageType} from this {fromStageType}. Take
          a moment to review the source stage before continuing.
        </p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-on-surface-variant hover:text-on-surface"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onProceed}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:opacity-90"
          >
            Proceed
          </button>
        </div>
      </div>
    </div>
  )
}

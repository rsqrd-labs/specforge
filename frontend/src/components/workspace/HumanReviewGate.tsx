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
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f172a]/60 p-4 backdrop-blur-sm"
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="w-full max-w-md rounded-xl border border-outline-variant bg-surface-container-lowest/90 p-6 shadow-[0_40px_100px_rgba(47,49,49,0.22)] backdrop-blur-xl">
        <div className="mb-1 text-xs font-semibold uppercase tracking-widest text-primary">
          Review gate
        </div>
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
            className="rounded-lg border border-outline-variant px-4 py-2 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onProceed}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-[0_4px_16px_rgba(143,78,0,0.22)] hover:opacity-90"
          >
            Proceed
          </button>
        </div>
      </div>
    </div>
  )
}

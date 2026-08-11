import { useRef } from "react"
import { Link } from "react-router"
import { useFocusTrap } from "../../hooks/useFocusTrap"

type CreditAction = "generate" | "regenerate" | "refine" | "patch"

interface CreditConfirmModalProps {
  action: CreditAction
  /** Credit cost of the action.  Defaults to CREDIT_COSTS[action] if omitted. */
  creditCost?: number
  /** Caller's current credit balance.  Defaults to 0 if omitted. */
  currentBalance?: number
  onConfirm: () => void
  onCancel: () => void
}

const CREDIT_COSTS: Record<CreditAction, number> = {
  generate: 10,
  regenerate: 10,
  refine: 3,
  patch: 10,
}

const ACTION_LABELS: Record<CreditAction, string> = {
  generate: "Generate",
  regenerate: "Regenerate",
  refine: "Refine",
  patch: "Patch coverage",
}

const ACTION_COPY: Record<CreditAction, string> = {
  generate:
    "Create the next ASDD artifact with the right level of architectural depth.",
  regenerate:
    "Replace this full stage with a fresh pass. Best for stale or oversized changes.",
  refine:
    "Preview a precise edit for the selected text before accepting changes.",
  patch:
    "Generate only the missing harness tests and merge them into this draft. " +
    "You are charged only when new test files are added.",
}

// The noun each action becomes in the out-of-credits message, e.g.
// "This generation needs 10 credits".
const ACTION_NOUN: Record<CreditAction, string> = {
  generate: "generation",
  regenerate: "regeneration",
  refine: "refinement",
  patch: "coverage patch",
}

export function CreditConfirmModal({
  action,
  creditCost,
  currentBalance,
  onConfirm,
  onCancel,
}: CreditConfirmModalProps) {
  const resolvedCost = creditCost ?? CREDIT_COSTS[action]
  const resolvedBalance = currentBalance ?? 0
  const remaining = resolvedBalance - resolvedCost
  const isInsufficient = resolvedBalance < resolvedCost
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onCancel)

  // Out of credits: rather than show a negative "After" figure and a dead
  // disabled action, present a clear recovery card pointing at billing.
  if (isInsufficient) {
    const actionNoun = ACTION_NOUN[action]
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
              You&apos;re out of credits
            </h2>
            <button onClick={onCancel} className="create-modal-close" aria-label="Close">✕</button>
          </div>

          <div className="create-modal-body">
            <div className="workspace-credit-empty" role="alert">
              <p className="workspace-credit-empty-lede">
                This {actionNoun} needs {resolvedCost} credits, and your balance is{" "}
                {resolvedBalance}. Top up your account to keep building — your work
                so far is saved.
              </p>
            </div>

            <div className="modal-footer">
              <button type="button" onClick={onCancel} className="modal-cancel">
                Not now
              </button>
              <Link to="/billing" className="modal-submit modal-submit-link" onClick={onCancel}>
                Buy credits
              </Link>
            </div>
          </div>
        </div>
      </div>
    )
  }

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
            {ACTION_LABELS[action]}
          </h2>
          <button onClick={onCancel} className="create-modal-close" aria-label="Close">✕</button>
        </div>

        <div className="create-modal-body">
          <p className="workspace-credit-value-copy">
            {ACTION_COPY[action]}
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
              <strong>
                <span>{remaining}</span> remaining
              </strong>
              <span className="sr-only">{remaining} remaining</span>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" onClick={onCancel} className="modal-cancel">
              Cancel
            </button>
            <button
              type="button"
              onClick={onConfirm}
              className="modal-submit"
            >
              {ACTION_LABELS[action]}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export { CREDIT_COSTS }

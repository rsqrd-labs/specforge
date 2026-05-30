import { useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import type { Stage, StageType } from "../../types/stage"

export const STORYBOARD_GENERATION_COST = 25

const STAGE_LABELS: Record<StageType, string> = {
  spec: "SPEC",
  plan: "PLAN",
  harness: "HARNESS",
  tasks: "TASKS",
}

const REQUIRED_STAGE_ORDER: StageType[] = ["spec", "plan", "harness", "tasks"]

const INCLUDED_ARTIFACTS = [
  { label: "Browser keynote", contractTerm: "browser" },
  { label: "Architecture reveal", contractTerm: "architecture" },
  { label: "Speaker notes", contractTerm: "speaker" },
  { label: "Walkthrough script", contractTerm: "demo" },
  { label: "Technical appendix", contractTerm: "appendix" },
  { label: "Share link", contractTerm: "share" },
  { label: "PDF downloads", contractTerm: "PDF" },
  { label: "HTML downloads", contractTerm: "HTML" },
]

export interface StoryboardPrerequisite {
  type: StageType
  status: Stage["status"] | "missing"
  isReady: boolean
}

export function getStoryboardPrerequisites(
  stages: Stage[],
): StoryboardPrerequisite[] {
  return REQUIRED_STAGE_ORDER.map((type) => {
    const stage = stages.find((candidate) => candidate.type === type)
    const status = stage?.status ?? "missing"
    return {
      type,
      status,
      isReady: status === "finalised",
    }
  })
}

export function canCreateStoryboardFromStages(stages: Stage[]): boolean {
  return getStoryboardPrerequisites(stages).every((item) => item.isReady)
}

function formatStatus(status: StoryboardPrerequisite["status"]): string {
  return status === "missing" ? "missing" : status.replace("_", " ")
}

interface CreateStoryboardModalProps {
  open: boolean
  stages: Stage[]
  currentBalance: number | null
  isPending?: boolean
  failureMessage?: string | null
  generateStoryboard: () => void | Promise<void>
  onClose: () => void
}

export function CreateStoryboardModal({
  open,
  stages,
  currentBalance,
  isPending = false,
  failureMessage,
  generateStoryboard,
  onClose,
}: CreateStoryboardModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const submitLockedRef = useRef(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  useFocusTrap(dialogRef, onClose)

  const prerequisites = useMemo(() => getStoryboardPrerequisites(stages), [stages])
  const allFinalised = prerequisites.every((item) => item.isReady)
  const hasStalePrerequisite = prerequisites.some((item) => item.status === "stale")
  const resolvedBalance = currentBalance ?? 0
  const remaining = resolvedBalance - STORYBOARD_GENERATION_COST
  const insufficientBalance = resolvedBalance < STORYBOARD_GENERATION_COST
  const balanceUnavailable = currentBalance === null
  const blocked =
    !allFinalised ||
    hasStalePrerequisite ||
    insufficientBalance ||
    balanceUnavailable ||
    isPending ||
    isSubmitting

  if (!open) return null

  async function handleConfirm() {
    if (blocked || submitLockedRef.current) return

    submitLockedRef.current = true
    setIsSubmitting(true)
    try {
      await generateStoryboard()
    } finally {
      submitLockedRef.current = false
      setIsSubmitting(false)
    }
  }

  return (
    <div
      className="create-modal-backdrop"
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="storyboard-create-title"
        className="create-modal storyboard-create-modal"
      >
        <div className="create-modal-header">
          <h2 id="storyboard-create-title" className="create-modal-title">
            Create Storyboard
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="create-modal-close"
            aria-label="Close"
            disabled={isPending || isSubmitting}
          >
            x
          </button>
        </div>

        <div className="create-modal-body storyboard-create-body">
          <p className="storyboard-create-lede">
            Turn the finalised workspace into a six-act product keynote with
            source-backed claims and presenter-ready artifacts.
          </p>

          <div className="workspace-credit-summary storyboard-credit-summary">
            <div>
              <span>Cost</span>
              <strong>{STORYBOARD_GENERATION_COST} credits</strong>
            </div>
            <div>
              <span>Current balance</span>
              <strong>{balanceUnavailable ? "Unavailable" : `${resolvedBalance} credits`}</strong>
            </div>
            <div className="workspace-credit-after">
              <span>Post-action balance</span>
              <strong className={insufficientBalance ? "danger" : ""}>
                {balanceUnavailable ? "Refresh required" : `${remaining} remaining`}
              </strong>
            </div>
          </div>

          <section
            className="storyboard-prereq-card"
            aria-label="Finalised-stage prerequisite state"
          >
            <div className="storyboard-prereq-header">
              <strong>Finalised-stage prerequisite</strong>
              <span>{allFinalised ? "All four ready" : "Action blocked"}</span>
            </div>
            <ul className="storyboard-prereq-list">
              {prerequisites.map((item) => (
                <li
                  key={item.type}
                  className={item.isReady ? "ready" : "blocked"}
                >
                  <span>{STAGE_LABELS[item.type]}</span>
                  <strong>{formatStatus(item.status)}</strong>
                </li>
              ))}
            </ul>
            {!allFinalised && (
              <p className="storyboard-prereq-warning">
                All four stages must be finalised before Storyboard generation.
                Stale or draft prerequisites need review first.
              </p>
            )}
          </section>

          <section className="storyboard-artifact-card" aria-label="Included artifacts">
            <strong>Included artifacts</strong>
            <ul>
              {INCLUDED_ARTIFACTS.map((artifact) => (
                <li key={artifact.label} data-artifact={artifact.contractTerm}>
                  {artifact.label}
                </li>
              ))}
            </ul>
          </section>

          {(failureMessage || insufficientBalance || balanceUnavailable) && (
            <div className="storyboard-modal-notice" role="status">
              {failureMessage && (
                <p>
                  {failureMessage} Any failed generation is refund-aware: credits
                  are returned when the backend cannot complete the Storyboard.
                </p>
              )}
              {balanceUnavailable && (
                <p>Refresh credits before creating the paid Storyboard.</p>
              )}
              {insufficientBalance && (
                <p>
                  Insufficient credit balance.{" "}
                  <Link to="/billing" onClick={onClose}>
                    Open Billing
                  </Link>
                  .
                </p>
              )}
            </div>
          )}

          <div className="modal-footer">
            <button
              type="button"
              onClick={onClose}
              className="modal-cancel"
              disabled={isPending || isSubmitting}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={blocked}
              className="modal-submit"
            >
              {isPending || isSubmitting ? "Starting..." : "Create Storyboard"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

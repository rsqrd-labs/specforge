/**
 * SpecClarificationModal — Phase 14 / T-USE-04
 *
 * Design (per Phase 14 Design Directive):
 *   Hierarchy → the question is the hero (Plus Jakarta Sans, saffron-anchored).
 *               `why_it_matters` is a slate whisper under it. Textarea sits on
 *               a glass surface. Skip is a quiet text-link at far left; the
 *               saffron Generate CTA lives at far right.
 *   Delight   → when the user begins typing in a textarea, that question's
 *               `why_it_matters` whisper fades to 60% opacity — a small
 *               acknowledgement that the user has engaged with this one.
 *   Tone      → a senior PM asking three sharp questions before recommending
 *               an approach. Not a survey, not a wizard. A short conversation.
 *
 * State machine (mounted only when conditions are met by the parent):
 *   "loading"    → POST /clarify in flight for a new clarification round
 *   "ready"      → questions rendered, user types
 *   "submitting" → PATCH /clarify in flight
 *   (bypassed)   → 204 from POST; we call onProceed([]) immediately so the
 *                  user never sees a flash. The modal is invisible in this
 *                  state — no spinner, no toast, no error.
 */
import { useEffect, useRef, useState } from "react"
import {
  persistClarification,
  requestClarification,
  type ClarifyAnswer,
  type ClarifyQuestion,
} from "../../services/api"
import type { ClarificationQA } from "../../types/workspace"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import { ActionAlertPanel } from "../shared/ActionAlert"

const ANSWER_MAX = 1000
const EMPTY_CLARIFICATION_ANSWERS: ClarificationQA[] = []
type SpecClarificationMode = "new" | "existing"

interface SpecClarificationModalProps {
  workspaceId: string
  mode?: SpecClarificationMode
  existingAnswers?: ClarificationQA[]
  onProceed: (answers: ClarifyAnswer[]) => void
  onCancel: () => void
}

type Phase = "loading" | "ready" | "submitting"

export function SpecClarificationModal({
  workspaceId,
  mode = "new",
  existingAnswers,
  onProceed,
  onCancel,
}: SpecClarificationModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const [phase, setPhase] = useState<Phase>("loading")
  const [questions, setQuestions] = useState<ClarifyQuestion[]>([])
  const [answers, setAnswers] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const proceededRef = useRef(false)
  const isExistingMode = mode === "existing"
  const savedClarificationAnswers =
    existingAnswers ?? EMPTY_CLARIFICATION_ANSWERS

  useFocusTrap(dialogRef, onCancel)

  // On mount: fetch questions only for a new round. Existing-answer retries
  // hydrate from saved workspace Q&A and never touch the clarification LLM.
  // A 204 (null) means the judge model could not produce questions — bypass
  // silently so the parent dispatches the standard generate. We do this exactly
  // once via proceededRef to keep React strict mode's double-invocation honest.
  useEffect(() => {
    let cancelled = false

    if (isExistingMode) {
      const savedAnswers = savedClarificationAnswers.filter(
        (entry) => entry.question.trim() && entry.answer.trim(),
      )
      if (savedAnswers.length === 0) {
        if (!proceededRef.current) {
          proceededRef.current = true
          onProceed([])
        }
        return () => {
          cancelled = true
        }
      }

      setQuestions(
        savedAnswers.map((entry) => ({
          question: entry.question,
          why_it_matters: "Previously answered.",
        })),
      )
      setAnswers(savedAnswers.map((entry) => entry.answer))
      setPhase("ready")
      return () => {
        cancelled = true
      }
    }

    requestClarification(workspaceId)
      .then((response) => {
        if (cancelled) return
        if (!response || response.questions.length === 0) {
          if (!proceededRef.current) {
            proceededRef.current = true
            onProceed([])
          }
          return
        }
        setQuestions(response.questions)
        setAnswers(response.questions.map(() => ""))
        setPhase("ready")
      })
      .catch(() => {
        // Best-effort: any unexpected error also bypasses the modal so the
        // user is never blocked from generating.
        if (cancelled) return
        if (!proceededRef.current) {
          proceededRef.current = true
          onProceed([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [savedClarificationAnswers, isExistingMode, workspaceId, onProceed])

  const canSubmit =
    phase === "ready" && answers.some((value) => value.trim().length > 0)

  const currentPayload = (): ClarifyAnswer[] =>
    questions
      .map((q, idx) => ({ question: q.question, answer: answers[idx].trim() }))
      .filter((entry) => entry.answer.length > 0)

  const savedExistingPayload = (): ClarifyAnswer[] =>
    savedClarificationAnswers
      .map((entry) => ({
        question: entry.question,
        answer: entry.answer.trim(),
      }))
      .filter((entry) => entry.question.trim() && entry.answer.length > 0)

  const handleSkip = () => {
    if (proceededRef.current) return
    proceededRef.current = true
    onProceed(isExistingMode ? savedExistingPayload() : [])
  }

  const handlePassiveClose = () => {
    if (isExistingMode) {
      onCancel()
      return
    }
    handleSkip()
  }

  const handleSubmit = async () => {
    if (!canSubmit || proceededRef.current) return
    const payload = currentPayload()
    if (payload.length === 0) return

    setError(null)
    setPhase("submitting")
    try {
      await persistClarification(
        workspaceId,
        payload,
        isExistingMode ? "existing" : "round",
      )
      proceededRef.current = true
      onProceed(payload)
    } catch {
      // Server-side validation rejection (e.g. expired round) is rare but
      // recoverable: surface a quiet inline error and let the user retry
      // or skip. We do NOT auto-bypass here — losing typed answers without
      // a word would feel broken.
      setPhase("ready")
      setError(
        isExistingMode
          ? "Couldn't save those edits. Use the saved answers, or try again."
          : "Couldn't save those answers. Skip to keep moving, or try again.",
      )
    }
  }

  // Loading state — single line of microcopy, gentle pulse. Invisible if
  // we bypass before the first paint.
  if (phase === "loading") {
    return (
      <div
        className="create-modal-backdrop"
        onClick={(event) =>
          event.target === event.currentTarget && handlePassiveClose()
        }
      >
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="clarify-modal-title"
          className="create-modal clarify-modal clarify-modal-loading"
        >
          <div className="create-modal-body clarify-modal-loading-body">
            <div className="clarify-modal-pulse" aria-hidden="true" />
            <p
              id="clarify-modal-title"
              className="clarify-modal-loading-copy"
              role="status"
            >
              Thinking of the right questions…
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      className="create-modal-backdrop"
      onClick={(event) =>
        event.target === event.currentTarget && handlePassiveClose()
      }
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="clarify-modal-title"
        className="create-modal clarify-modal"
      >
        <div className="create-modal-header clarify-modal-header">
          <div>
            <h2 id="clarify-modal-title" className="create-modal-title">
              {isExistingMode
                ? "Review your previous answers"
                : "Sharpen the brief"}
            </h2>
            <p className="clarify-modal-subtitle">
              {isExistingMode
                ? "Use the answers already saved for this workspace, or adjust only what changed."
                : "A few targeted questions before we draft your spec."}
            </p>
          </div>
          <button
            type="button"
            onClick={handlePassiveClose}
            className="create-modal-close"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="create-modal-body clarify-modal-body">
          {isExistingMode && (
            <p className="clarify-modal-note">
              These answers are already saved. Edit only what changed.
            </p>
          )}

          {questions.map((q, idx) => {
            const typed = answers[idx].trim().length > 0
            return (
              <div key={q.question} className="clarify-question">
                <label
                  className="clarify-question-label"
                  htmlFor={`clarify-answer-${idx}`}
                >
                  {q.question}
                </label>
                {!isExistingMode && (
                  <p
                    className={
                      typed
                        ? "clarify-question-why clarify-question-why-engaged"
                        : "clarify-question-why"
                    }
                  >
                    {q.why_it_matters}
                  </p>
                )}
                <textarea
                  id={`clarify-answer-${idx}`}
                  className="clarify-modal-textarea"
                  rows={3}
                  maxLength={ANSWER_MAX}
                  value={answers[idx]}
                  placeholder="A sentence or two is plenty."
                  onChange={(event) => {
                    const next = [...answers]
                    next[idx] = event.target.value
                    setAnswers(next)
                  }}
                  disabled={phase === "submitting"}
                />
                <div className="clarify-question-char-count">
                  {answers[idx].length}/{ANSWER_MAX}
                </div>
              </div>
            )
          })}

          {error && (
            <ActionAlertPanel
              severity="error"
              title="Answers could not be saved"
              message={error}
              recovery={
                isExistingMode
                  ? "Your edits are still here. Use the saved answers or try saving again."
                  : "Your typed answers are still here. Try again or skip to keep moving."
              }
              source="Clarification"
              onDismiss={() => setError(null)}
            />
          )}

          <div className="modal-footer clarify-modal-footer">
            <button
              type="button"
              onClick={handleSkip}
              className="clarify-modal-skip"
              disabled={phase === "submitting"}
              aria-label={
                isExistingMode
                  ? "Use saved clarification answers and retry generation"
                  : "Skip clarification and go straight to drafting"
              }
            >
              {isExistingMode ? "Use answers" : "Skip"}
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit}
              className="modal-submit"
              aria-label={
                isExistingMode
                  ? "Save edited clarification answers and retry generation"
                  : "Generate from clarification answers"
              }
            >
              {phase === "submitting"
                ? "Saving…"
                : isExistingMode
                  ? "Save and retry"
                  : "Generate"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SpecClarificationModal

import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { STARTER_WORKSPACES } from "../../config/starterWorkspaces"
import { featureFlags } from "../../config/featureFlags"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import { useScrollLock } from "../../hooks/useScrollLock"
import { getApiErrorMessage } from "../../services/api"
import { useWorkspaceStore } from "../../store/workspaceStore"
import type { Template } from "../../types/template"
import type {
  CreateWorkspacePayload,
  TargetAgent,
  WorkspaceMode,
} from "../../types/workspace"
import { ActionAlertPanel } from "../shared/ActionAlert"

interface CreateWorkspaceModalProps {
  onClose: () => void
  initialName?: string
  initialStatement?: string
  initialTemplate?: Template | null
  balance: number | null
  generationCost: number
}

const MIN_STATEMENT = 50
const MAX_STATEMENT = 10000

// Demo Day mode (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md §10 Phase 4). The
// whole selector is gated behind `featureFlags.demoDayMode`; when off, the modal
// is byte-identical to the standard create flow (the §4 regression pin).
const MODE_OPTIONS: { id: WorkspaceMode; name: string; desc: string }[] = [
  {
    id: "standard",
    name: "Standard",
    desc: "Full four-stage spec for any project",
  },
  {
    id: "demo_day",
    name: "Demo Day",
    desc: "Build-ready handoff for a ~5h prototype",
  },
]

// The two supported test-executing agents (plan §3). The choice only selects the
// operating-manual filename/idiom in the export bundle (CLAUDE.md vs AGENTS.md).
const AGENT_OPTIONS: { id: TargetAgent; name: string; desc: string }[] = [
  { id: "claude_code", name: "Claude Code", desc: "CLAUDE.md operating manual" },
  { id: "codex", name: "Codex", desc: "AGENTS.md operating manual" },
  { id: "both", name: "Both", desc: "CLAUDE.md and AGENTS.md" },
]

// Default agent for a Demo Day workspace. The backend requires target_agent when
// mode is demo_day, so the selector is never left null.
const DEFAULT_TARGET_AGENT: TargetAgent = "claude_code"

// Time-budget presets (minutes). 5h is the default/untouched value — selecting
// it produces the same payload shape a client omitting the field would (the
// regression pin every existing Demo Day workspace relies on).
const TIME_BUDGET_OPTIONS: { minutes: number; label: string }[] = [
  { minutes: 300, label: "5h" },
  { minutes: 480, label: "8h" },
  { minutes: 720, label: "12h" },
  { minutes: 1440, label: "24h" },
]
const DEFAULT_TIME_BUDGET_MINUTES = 300

export function CreateWorkspaceModal({
  onClose,
  initialName = "",
  initialStatement = "",
  initialTemplate = null,
  balance,
  generationCost,
}: CreateWorkspaceModalProps) {
  const navigate = useNavigate()
  const { createWorkspace } = useWorkspaceStore()

  const [name, setName] = useState(initialName)
  const [statement, setStatement] = useState(initialStatement)
  const [activeTemplate, setActiveTemplate] = useState<Template | null>(
    initialTemplate,
  )
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  // Demo Day mode selection — only surfaced when the build flag is on.
  const demoDayEnabled = featureFlags.demoDayMode
  const [mode, setMode] = useState<WorkspaceMode>("standard")
  const [targetAgent, setTargetAgent] = useState<TargetAgent>(DEFAULT_TARGET_AGENT)
  const [timeBudgetMinutes, setTimeBudgetMinutes] = useState<number>(
    DEFAULT_TIME_BUDGET_MINUTES,
  )
  const [restrictedEnvironment, setRestrictedEnvironment] = useState(false)
  const isDemoDay = demoDayEnabled && mode === "demo_day"

  const dialogRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLFormElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  useFocusTrap(dialogRef, onClose, nameInputRef)
  // Lock the dashboard behind the modal so a wheel/trackpad gesture only ever
  // scrolls the card — never the blurred page behind it, wherever the pointer is.
  useScrollLock()

  function validate() {
    const errs: Record<string, string> = {}
    if (!name.trim()) errs.name = "Name is required"
    if (statement.length < MIN_STATEMENT)
      errs.statement = `At least ${MIN_STATEMENT} characters required`
    if (statement.length > MAX_STATEMENT)
      errs.statement = `Maximum ${MAX_STATEMENT} characters`
    return errs
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length > 0) {
      setErrors(errs)
      return
    }
    setIsSubmitting(true)
    try {
      const payload: CreateWorkspacePayload = {
        name: name.trim(),
        problem_statement: statement,
        template_slug: activeTemplate?.slug ?? null,
        target_agent: targetAgent,
      }
      // Mode remains Demo-Day-only; agent instructions apply to every workspace.
      if (isDemoDay) {
        payload.mode = "demo_day"
        payload.time_budget_minutes = timeBudgetMinutes
        payload.restricted_environment = restrictedEnvironment
      }
      const ws = await createWorkspace(payload)
      void navigate(`/workspace/${ws.id}`)
    } catch (error) {
      setErrors({
        submit: getApiErrorMessage(
          error,
          "Failed to create workspace. Please try again.",
        ),
      })
      setIsSubmitting(false)
    }
  }

  // Forward wheel gestures that land outside the scrollable body (the backdrop
  // padding or the fixed header) into the card, so a scroll anywhere over the
  // open modal scrolls the card rather than doing nothing.
  function handleBackdropWheel(e: React.WheelEvent) {
    const body = bodyRef.current
    if (!body || body.contains(e.target as Node)) return
    body.scrollTop += e.deltaY
  }

  const isUnderMin = statement.length < MIN_STATEMENT
  const minFillPct = Math.min((statement.length / MIN_STATEMENT) * 100, 100)
  const isOverMax = statement.length > MAX_STATEMENT
  const isLowBalance = balance !== null && balance < generationCost

  return (
    <div
      className="create-modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      onWheel={handleBackdropWheel}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-workspace-title"
        className="create-modal"
      >
        <div className="create-modal-header">
          <h2 id="create-workspace-title" className="create-modal-title">
            Start a Workspace
          </h2>
          <button onClick={onClose} className="create-modal-close" aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <form ref={bodyRef} onSubmit={(e) => void handleSubmit(e)} className="create-modal-body">

          {activeTemplate && (
            <div className="modal-template-provenance">
              Started from <strong>{activeTemplate.name}</strong>
              {" · "}
              <button
                type="button"
                className="modal-template-clear"
                onClick={() => {
                  setActiveTemplate(null)
                  setName("")
                  setStatement("")
                  setErrors({})
                }}
              >
                clear
              </button>
            </div>
          )}

          {/* Template chips */}
          <div className="modal-templates">
            <span className="modal-templates-label">Quick start</span>
            {STARTER_WORKSPACES.map((s) => (
              <button
                key={s.name}
                type="button"
                className="modal-template-chip"
                onClick={() => {
                  setName(s.name)
                  setStatement(s.statement)
                  setErrors({})
                }}
              >
                {s.name}
              </button>
            ))}
          </div>

          {/* Idea Name */}
          <div>
            <label className="modal-label" htmlFor="ws-name">Idea Name</label>
            <input
              id="ws-name"
              ref={nameInputRef}
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                if (errors.name) setErrors((prev) => ({ ...prev, name: "" }))
              }}
              maxLength={200}
              className={`modal-input${errors.name ? " error" : ""}`}
              placeholder="AI onboarding coach"
            />
            {errors.name && <p className="modal-error">{errors.name}</p>}
          </div>

          {/* Problem statement */}
          <div>
            <label className="modal-label" htmlFor="ws-statement">What should this become?</label>
            <textarea
              id="ws-statement"
              value={statement}
              onChange={(e) => {
                setStatement(e.target.value)
                if (errors.statement) setErrors((prev) => ({ ...prev, statement: "" }))
              }}
              rows={5}
              maxLength={MAX_STATEMENT}
              className={`modal-input resize-none${errors.statement ? " error" : ""}`}
              placeholder="Describe the user, the problem, the rough shape of the solution, and what would make it worth shipping."
            />
            <div className="modal-char-row">
              {isUnderMin ? (
                <div className="modal-min-progress" role="progressbar" aria-valuenow={statement.length} aria-valuemin={0} aria-valuemax={MIN_STATEMENT}>
                  <div className="modal-min-progress-fill" style={{ width: `${minFillPct}%` }} />
                </div>
              ) : (
                <span />
              )}
              <span className={`modal-char-count${isOverMax ? " over" : ""}${isUnderMin && statement.length > 0 ? " building" : ""}`}>
                {isUnderMin
                  ? `${statement.length} / ${MIN_STATEMENT} min`
                  : `${statement.length.toLocaleString()} / ${MAX_STATEMENT.toLocaleString()}`}
              </span>
            </div>
            {errors.statement && <p className="modal-error">{errors.statement}</p>}
          </div>

          {/* Mode selector (Demo Day, build-flag gated). Above the Advanced
              disclosure per plan §10 Phase 4. Hidden entirely when the flag is
              off so the standard modal is unchanged. */}
          {demoDayEnabled && (
            <div className="modal-mode">
              <span className="modal-label">Mode</span>
              <div className="modal-mode-grid">
                {MODE_OPTIONS.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMode(m.id)}
                    aria-pressed={mode === m.id}
                    className={`provider-pill${mode === m.id ? " selected" : ""}`}
                  >
                    <span>{m.name}</span>
                    <small className="modal-provider-desc">{m.desc}</small>
                  </button>
                ))}
              </div>

            </div>
          )}

          {/* Time budget + restricted-environment (Demo Day only). Untouched
              defaults (5h, unrestricted) reproduce today's behavior exactly. */}
          {isDemoDay && (
            <div className="modal-mode">
              <span className="modal-label">Build time budget</span>
              <div className="modal-mode-grid">
                {TIME_BUDGET_OPTIONS.map((opt) => (
                  <button
                    key={opt.minutes}
                    type="button"
                    onClick={() => setTimeBudgetMinutes(opt.minutes)}
                    aria-pressed={timeBudgetMinutes === opt.minutes}
                    className={`provider-pill${timeBudgetMinutes === opt.minutes ? " selected" : ""}`}
                  >
                    <span>{opt.label}</span>
                  </button>
                ))}
              </div>
              <p className="modal-mode-hint">
                Advisory only — bigger budgets deepen the same one happy path
                (more edge cases, more tasks), never multiple features.
              </p>

              <button
                type="button"
                role="switch"
                aria-checked={restrictedEnvironment}
                onClick={() => setRestrictedEnvironment((v) => !v)}
                className={`provider-pill${restrictedEnvironment ? " selected" : ""}`}
              >
                <span>Locked-down environment</span>
                <small className="modal-provider-desc">
                  No Docker, no admin/sudo installs (e.g. a hackathon laptop)
                </small>
              </button>
            </div>
          )}

          <div className="modal-agent">
            <span className="modal-label">Coding agent instructions</span>
            <div className="modal-mode-grid">
              {AGENT_OPTIONS.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setTargetAgent(a.id)}
                  aria-pressed={targetAgent === a.id}
                  className={`provider-pill${targetAgent === a.id ? " selected" : ""}`}
                >
                  <span>{a.name}</span>
                  <small className="modal-provider-desc">{a.desc}</small>
                </button>
              ))}
            </div>
            <p className="modal-mode-hint">
              Selected instruction files are included in ZIP and GitHub exports.
            </p>
          </div>

          {/* Pipeline preview. Demo Day appends the rubric-aware handoff step so
              the user sees the build-ready bundle is the deliverable. */}
          <div className="modal-pipeline-preview" aria-label="What gets generated">
            <span className="modal-pipeline-label">Generates</span>
            {["Spec", "Plan", "Harness", "Tasks"].map((stage, i, arr) => (
              <span key={stage} className="modal-pipeline-stages">
                <span className="modal-pipeline-step">{stage}</span>
                {(i < arr.length - 1 || isDemoDay) && (
                  <span className="modal-pipeline-arrow">→</span>
                )}
              </span>
            ))}
            {isDemoDay && (
              <span className="modal-pipeline-stages">
                <span className="modal-pipeline-step handoff">
                  Build-ready handoff
                </span>
              </span>
            )}
          </div>

          {errors.submit && (
            <ActionAlertPanel
              severity="error"
              title="Workspace could not be created"
              message={errors.submit}
              recovery="Your draft is still in this form. Check the statement and try again."
              source="Dashboard"
              onDismiss={() => setErrors((prev) => ({ ...prev, submit: "" }))}
            />
          )}

          <div className="modal-footer">
            <div className="modal-credit-hint" aria-live="polite">
              <span className={`modal-credit-cost${isLowBalance ? " low" : ""}`}>
                {generationCost} credits / stage
              </span>
              {balance !== null && (
                <span className={`modal-credit-balance${isLowBalance ? " low" : ""}`}>
                  {isLowBalance ? `⚠ only ${balance} left` : `${balance} remaining`}
                </span>
              )}
            </div>
            <div className="modal-footer-actions">
              <button type="button" onClick={onClose} className="modal-cancel">
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="modal-submit"
                aria-label="Generate workspace spec"
              >
                {isSubmitting ? "Generating spec…" : "Generate"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

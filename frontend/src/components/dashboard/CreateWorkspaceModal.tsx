import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { STARTER_WORKSPACES } from "../../config/starterWorkspaces"
import { PROVIDERS } from "../../config/providers"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import { getApiErrorMessage, getProviders } from "../../services/api"
import { useWorkspaceStore } from "../../store/workspaceStore"
import type { Template } from "../../types/template"
import type { AIProvider } from "../../types/workspace"
import type { Provider } from "../../services/api"

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

const PROVIDER_DESCRIPTIONS: Record<string, string> = {
  anthropic: "Best for nuanced reasoning and long-form specs",
  openai: "Strong general-purpose generation",
  google: "Good balance of speed and quality",
}

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
  const [providers, setProviders] = useState<Provider[]>(PROVIDERS)
  const [provider, setProvider] = useState<AIProvider>(
    (initialTemplate?.suggested_provider as AIProvider | undefined) ?? "openai",
  )
  const [activeTemplate, setActiveTemplate] = useState<Template | null>(
    initialTemplate,
  )
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false)

  const dialogRef = useRef<HTMLDivElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  useFocusTrap(dialogRef, onClose, nameInputRef)

  const selectableProviders = providers.filter((p) => p.selectable)
  const selectedProvider = providers.find((p) => p.id === provider)

  function handleProviderChange(newProvider: AIProvider) {
    const candidate = providers.find((p) => p.id === newProvider)
    if (!candidate?.selectable) return
    setProvider(newProvider)
  }

  useEffect(() => {
    let cancelled = false
    getProviders()
      .then((catalog) => {
        if (cancelled) return
        setProviders(catalog.providers)
        const firstSelectable = catalog.providers.find((p) => p.selectable)
        if (firstSelectable && !catalog.providers.find((p) => p.id === provider)?.selectable) {
          setProvider(firstSelectable.id)
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [provider])

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
      const ws = await createWorkspace({
        name: name.trim(),
        problem_statement: statement,
        provider,
        template_slug: activeTemplate?.slug ?? null,
      })
      navigate(`/workspace/${ws.id}`)
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

  const isUnderMin = statement.length < MIN_STATEMENT
  const minFillPct = Math.min((statement.length / MIN_STATEMENT) * 100, 100)
  const isOverMax = statement.length > MAX_STATEMENT
  const isLowBalance = balance !== null && balance < generationCost

  return (
    <div
      className="create-modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
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

        <form onSubmit={(e) => void handleSubmit(e)} className="create-modal-body">

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

          {/* Advanced (provider) */}
          <div className="modal-advanced">
            <button
              type="button"
              className="modal-advanced-toggle"
              aria-expanded={isAdvancedOpen}
              onClick={() => setIsAdvancedOpen((v) => !v)}
            >
              <span className="modal-advanced-label">AI Provider</span>
              {!isAdvancedOpen && selectedProvider && (
                <span className="modal-advanced-summary">{selectedProvider.name}</span>
              )}
              <svg
                className="modal-advanced-chevron"
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                aria-hidden="true"
                style={{ transform: isAdvancedOpen ? "rotate(180deg)" : "rotate(0deg)" }}
              >
                <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>

            {isAdvancedOpen && (
              <div className="modal-advanced-body">
                <div className="provider-grid">
                  {providers.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => handleProviderChange(p.id)}
                      disabled={!p.selectable}
                      title={p.message}
                      className={[
                        "provider-pill",
                        provider === p.id ? "selected" : "",
                        !p.selectable ? "disabled" : "",
                        p.health === "degraded" ? "degraded" : "",
                        p.health === "unhealthy" ? "unhealthy" : "",
                      ].filter(Boolean).join(" ")}
                    >
                      <span>{p.name}</span>
                      {!p.configured
                        ? <small>Not configured</small>
                        : p.health !== "healthy"
                        ? <small>{p.health}</small>
                        : <small className="modal-provider-desc">{PROVIDER_DESCRIPTIONS[p.id] ?? ""}</small>
                      }
                    </button>
                  ))}
                </div>
                {selectableProviders.length === 0 && (
                  <p className="modal-error">
                    No model providers are configured. Add at least one provider API key
                    on the backend.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Pipeline preview */}
          <div className="modal-pipeline-preview" aria-label="What gets generated">
            <span className="modal-pipeline-label">Generates</span>
            {["Spec", "Plan", "Harness", "Tasks"].map((stage, i, arr) => (
              <span key={stage} className="modal-pipeline-stages">
                <span className="modal-pipeline-step">{stage}</span>
                {i < arr.length - 1 && <span className="modal-pipeline-arrow">→</span>}
              </span>
            ))}
          </div>

          {errors.submit && <p className="modal-error">{errors.submit}</p>}

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
                disabled={isSubmitting || selectableProviders.length === 0}
                className="modal-submit"
              >
                {isSubmitting ? "Generating spec…" : "Start shaping it"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

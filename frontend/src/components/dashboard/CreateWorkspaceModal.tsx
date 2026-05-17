import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { PROVIDERS } from "../../config/providers"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import { getApiErrorMessage, getProviders } from "../../services/api"
import { useWorkspaceStore } from "../../store/workspaceStore"
import type { AIProvider } from "../../types/workspace"
import type { Provider } from "../../services/api"

interface CreateWorkspaceModalProps {
  onClose: () => void
  initialName?: string
  initialStatement?: string
}

const MIN_STATEMENT = 50
const MAX_STATEMENT = 10000

export function CreateWorkspaceModal({
  onClose,
  initialName = "",
  initialStatement = "",
}: CreateWorkspaceModalProps) {
  const navigate = useNavigate()
  const { createWorkspace } = useWorkspaceStore()

  const [name, setName] = useState(initialName)
  const [statement, setStatement] = useState(initialStatement)
  const [providers, setProviders] = useState<Provider[]>(PROVIDERS)
  const [provider, setProvider] = useState<AIProvider>("openai")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onClose)

  const selectableProviders = providers.filter((p) => p.selectable)

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
            ✕
          </button>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="create-modal-body">
          <div>
            <label className="modal-label">Idea Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                if (errors.name) setErrors((prev) => ({ ...prev, name: "" }))
              }}
              className={`modal-input${errors.name ? " error" : ""}`}
              placeholder="AI onboarding coach"
            />
            {errors.name && <p className="modal-error">{errors.name}</p>}
          </div>

          <div>
            <label className="modal-label">What should this become?</label>
            <textarea
              value={statement}
              onChange={(e) => {
                setStatement(e.target.value)
                if (errors.statement) setErrors((prev) => ({ ...prev, statement: "" }))
              }}
              rows={5}
              className={`modal-input resize-none${errors.statement ? " error" : ""}`}
              placeholder="Describe the user, the problem, the rough shape of the solution, and what would make it worth shipping."
            />
            <div className="mt-1.5 flex items-center justify-between">
              {errors.statement ? (
                <p className="modal-error">{errors.statement}</p>
              ) : (
                <span />
              )}
              <p className={`modal-char-count${statement.length > MAX_STATEMENT ? " over" : ""}`}>
                {statement.length}/{MAX_STATEMENT}
              </p>
            </div>
          </div>

          <div>
            <label className="modal-label">Provider</label>
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
                  {!p.configured && <small>Not configured</small>}
                  {p.configured && p.health !== "healthy" && (
                    <small>{p.health}</small>
                  )}
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

          {errors.submit && <p className="modal-error">{errors.submit}</p>}

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="modal-cancel">
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || selectableProviders.length === 0}
              className="modal-submit"
            >
              {isSubmitting ? "Shaping..." : "Start shaping it"}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

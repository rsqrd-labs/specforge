import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { PROVIDERS } from "../../config/providers"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import { getApiErrorMessage } from "../../services/api"
import { useWorkspaceStore } from "../../store/workspaceStore"
import type { AIProvider } from "../../types/workspace"

interface CreateWorkspaceModalProps {
  onClose: () => void
}

const MIN_STATEMENT = 50
const MAX_STATEMENT = 10000

export function CreateWorkspaceModal({ onClose }: CreateWorkspaceModalProps) {
  const navigate = useNavigate()
  const { createWorkspace } = useWorkspaceStore()

  const [name, setName] = useState("")
  const [statement, setStatement] = useState("")
  const [provider, setProvider] = useState<AIProvider>("anthropic")
  const [model, setModel] = useState("claude-sonnet-4-6")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(dialogRef, onClose)

  const availableModels = PROVIDERS.find((p) => p.id === provider)?.models ?? []

  function handleProviderChange(newProvider: AIProvider) {
    setProvider(newProvider)
    const models = PROVIDERS.find((p) => p.id === newProvider)?.models ?? []
    setModel(models[0]?.id ?? "")
  }

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
        model,
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
            New Workspace
          </h2>
          <button onClick={onClose} className="create-modal-close" aria-label="Close">
            ✕
          </button>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="create-modal-body">
          <div>
            <label className="modal-label">Workspace Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                if (errors.name) setErrors((prev) => ({ ...prev, name: "" }))
              }}
              className={`modal-input${errors.name ? " error" : ""}`}
              placeholder="My Todo App"
            />
            {errors.name && <p className="modal-error">{errors.name}</p>}
          </div>

          <div>
            <label className="modal-label">Problem Statement</label>
            <textarea
              value={statement}
              onChange={(e) => {
                setStatement(e.target.value)
                if (errors.statement) setErrors((prev) => ({ ...prev, statement: "" }))
              }}
              rows={5}
              className={`modal-input resize-none${errors.statement ? " error" : ""}`}
              placeholder="Describe what you want to build in detail — the more context, the better the spec…"
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
              {PROVIDERS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => handleProviderChange(p.id as AIProvider)}
                  className={`provider-pill${provider === p.id ? " selected" : ""}`}
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="modal-label">Model</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="modal-input"
            >
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          {errors.submit && <p className="modal-error">{errors.submit}</p>}

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="modal-cancel">
              Cancel
            </button>
            <button type="submit" disabled={isSubmitting} className="modal-submit">
              {isSubmitting ? "Creating…" : "Create Workspace"}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

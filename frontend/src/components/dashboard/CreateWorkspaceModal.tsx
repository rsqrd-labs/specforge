import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { PROVIDERS } from "../../config/providers"
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

  const availableModels =
    PROVIDERS.find((p) => p.id === provider)?.models ?? []

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
    } catch {
      setErrors({ submit: "Failed to create workspace. Please try again." })
      setIsSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-surface rounded-xl w-full max-w-lg shadow-xl">
        <div className="flex items-center justify-between p-6 border-b border-outline-variant">
          <h2 className="text-lg font-semibold text-on-surface">
            New Workspace
          </h2>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-on-surface"
          >
            ✕
          </button>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-on-surface mb-1">
              Workspace Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-outline-variant bg-surface-container text-on-surface focus:outline-none focus:border-primary"
              placeholder="My Todo App"
            />
            {errors.name && (
              <p className="text-xs text-error mt-1">{errors.name}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-on-surface mb-1">
              Problem Statement
            </label>
            <textarea
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 rounded-lg border border-outline-variant bg-surface-container text-on-surface focus:outline-none focus:border-primary resize-none"
              placeholder="Describe what you want to build..."
            />
            <div className="flex justify-between items-center mt-1">
              {errors.statement ? (
                <p className="text-xs text-error">{errors.statement}</p>
              ) : (
                <span />
              )}
              <p
                className={`text-xs ${
                  statement.length > MAX_STATEMENT
                    ? "text-error"
                    : "text-on-surface-variant"
                }`}
              >
                {statement.length}/{MAX_STATEMENT}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-on-surface mb-1">
                Provider
              </label>
              <select
                value={provider}
                onChange={(e) =>
                  handleProviderChange(e.target.value as AIProvider)
                }
                className="w-full px-3 py-2 rounded-lg border border-outline-variant bg-surface-container text-on-surface focus:outline-none focus:border-primary"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface mb-1">
                Model
              </label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-outline-variant bg-surface-container text-on-surface focus:outline-none focus:border-primary"
              >
                {availableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {errors.submit && (
            <p className="text-xs text-error">{errors.submit}</p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-on-surface-variant hover:text-on-surface"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 text-sm font-medium bg-primary text-on-primary rounded-lg hover:opacity-90 disabled:opacity-50"
            >
              {isSubmitting ? "Creating..." : "Create Workspace"}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

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

  const inputClass =
    "w-full rounded-lg border border-outline-variant bg-surface px-3 py-2.5 text-sm text-on-surface outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/10"

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#0f172a]/60 p-4 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-lg rounded-xl border border-outline-variant bg-surface-container-lowest/90 shadow-[0_40px_100px_rgba(47,49,49,0.22)] backdrop-blur-xl">
        <div className="flex items-center justify-between border-b border-outline-variant px-6 py-4">
          <h2 className="text-base font-semibold text-on-surface">
            New Workspace
          </h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            ✕
          </button>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4 p-6">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
              Workspace Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
              placeholder="My Todo App"
            />
            {errors.name && (
              <p className="mt-1 text-xs text-error">{errors.name}</p>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
              Problem Statement
            </label>
            <textarea
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              rows={4}
              className={`${inputClass} resize-none`}
              placeholder="Describe what you want to build..."
            />
            <div className="mt-1 flex items-center justify-between">
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
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
                Provider
              </label>
              <select
                value={provider}
                onChange={(e) =>
                  handleProviderChange(e.target.value as AIProvider)
                }
                className={inputClass}
              >
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
                Model
              </label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className={inputClass}
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
              className="rounded-lg border border-outline-variant px-4 py-2 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-[0_4px_16px_rgba(143,78,0,0.22)] transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {isSubmitting ? "Creating..." : "Create Workspace"}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

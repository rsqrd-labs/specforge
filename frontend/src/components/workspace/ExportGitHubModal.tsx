import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"

import { useFocusTrap } from "../../hooks/useFocusTrap"
import {
  exportWorkspaceToGitHub,
  getApiErrorMessage,
  type GitHubExportResponse,
} from "../../services/api"

interface ExportGitHubModalProps {
  workspaceId: string
  workspaceName: string
  isConnected: boolean
  taskCount: number
  onClose: () => void
}

type Phase = "configure" | "progress" | "success" | "error"

const REPO_NAME_PATTERN = /^[a-zA-Z0-9._-]+$/
const REPO_NAME_MAX = 100

const PROGRESS_STEPS = [
  "Creating repo…",
  "Pushing files…",
  "Creating issues…",
]
const PROGRESS_INTERVAL_MS = 3000

function slugifyWorkspaceName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, REPO_NAME_MAX)
}

export function ExportGitHubModal({
  workspaceId,
  workspaceName,
  isConnected,
  taskCount,
  onClose,
}: ExportGitHubModalProps) {
  const navigate = useNavigate()
  const dialogRef = useRef<HTMLDivElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  useFocusTrap(dialogRef, onClose, nameInputRef)

  const initialRepoName = useMemo(
    () => slugifyWorkspaceName(workspaceName) || "spec-export",
    [workspaceName],
  )

  const [repoName, setRepoName] = useState(initialRepoName)
  const [visibility, setVisibility] = useState<"public" | "private">("public")
  const [phase, setPhase] = useState<Phase>("configure")
  const [progressLabel, setProgressLabel] = useState(PROGRESS_STEPS[0])
  const [result, setResult] = useState<GitHubExportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [repoNameError, setRepoNameError] = useState<string | null>(null)

  // Drive the progress-label cycle while the request is in flight.
  useEffect(() => {
    if (phase !== "progress") {
      return undefined
    }
    let index = 0
    setProgressLabel(PROGRESS_STEPS[index])
    const handle = window.setInterval(() => {
      index = Math.min(index + 1, PROGRESS_STEPS.length - 1)
      setProgressLabel(PROGRESS_STEPS[index])
    }, PROGRESS_INTERVAL_MS)
    return () => window.clearInterval(handle)
  }, [phase])

  function validateRepoName(value: string): string | null {
    if (!value.trim()) {
      return "Repo name is required."
    }
    if (value.length > REPO_NAME_MAX) {
      return `Maximum ${REPO_NAME_MAX} characters.`
    }
    if (!REPO_NAME_PATTERN.test(value)) {
      return "Use letters, digits, '.', '_' or '-' only."
    }
    return null
  }

  function handleRepoNameBlur() {
    setRepoNameError(validateRepoName(repoName))
  }

  async function handleSubmit() {
    const validation = validateRepoName(repoName)
    if (validation) {
      setRepoNameError(validation)
      return
    }

    setPhase("progress")
    setError(null)

    // Client-side timeout: abort the export request after 30 seconds so a
    // hung API call resolves to a recoverable error state rather than an
    // infinite spinner.  L-4 — T-189b.
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 30_000)
    try {
      const response = await exportWorkspaceToGitHub(workspaceId, {
        repo_name: repoName,
        visibility,
      })
      setResult(response)
      setPhase("success")
    } catch (caught) {
      const isAbort =
        caught instanceof DOMException && caught.name === "AbortError"
      setError(
        isAbort
          ? "Export timed out — please retry."
          : getApiErrorMessage(caught, "Export failed. Please try again."),
      )
      setPhase("error")
    } finally {
      clearTimeout(timeout)
    }
  }

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    // Don't allow click-out dismiss while a request is in flight.
    if (phase === "progress") return
    if (e.target === e.currentTarget) onClose()
  }

  function handleGoToSettings() {
    onClose()
    navigate("/settings")
  }

  function handleOpenRepo() {
    if (result?.repo_url) {
      window.open(result.repo_url, "_blank", "noopener,noreferrer")
    }
    onClose()
  }

  const submitDisabled =
    phase !== "configure" ||
    !repoName.trim() ||
    !!validateRepoName(repoName)

  return (
    <div className="create-modal-backdrop" onClick={handleBackdropClick}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="github-export-modal-title"
        className="create-modal"
      >
        <div className="create-modal-header">
          <h2 id="github-export-modal-title" className="create-modal-title">
            Export to GitHub
          </h2>
          <button
            type="button"
            className="create-modal-close"
            aria-label="Close"
            onClick={onClose}
            disabled={phase === "progress"}
          >
            ✕
          </button>
        </div>

        <div className="create-modal-body">
          {!isConnected ? (
            <div className="github-modal-not-connected">
              <p>
                Connect your GitHub account in Settings to export to a repo.
              </p>
              <button
                type="button"
                className="modal-submit"
                onClick={handleGoToSettings}
              >
                Go to Settings →
              </button>
            </div>
          ) : phase === "configure" ? (
            <>
              <label className="modal-label" htmlFor="github-repo-name">
                Repository name
              </label>
              <input
                ref={nameInputRef}
                id="github-repo-name"
                className="modal-input"
                type="text"
                value={repoName}
                onChange={(e) => {
                  setRepoName(e.target.value)
                  if (repoNameError) {
                    setRepoNameError(validateRepoName(e.target.value))
                  }
                }}
                onBlur={handleRepoNameBlur}
                maxLength={REPO_NAME_MAX}
                spellCheck={false}
                autoComplete="off"
              />
              {repoNameError && (
                <p className="modal-error">{repoNameError}</p>
              )}

              <label className="modal-label">Visibility</label>
              <div className="github-modal-visibility-grid">
                <button
                  type="button"
                  className={`github-modal-visibility-btn ${
                    visibility === "public" ? "selected" : ""
                  }`}
                  onClick={() => setVisibility("public")}
                  aria-pressed={visibility === "public"}
                >
                  Public
                </button>
                <button
                  type="button"
                  className={`github-modal-visibility-btn ${
                    visibility === "private" ? "selected" : ""
                  }`}
                  onClick={() => setVisibility("private")}
                  aria-pressed={visibility === "private"}
                >
                  Private
                </button>
              </div>

              <div className="github-modal-issue-pill">
                {taskCount} issue{taskCount === 1 ? "" : "s"} will be created
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="modal-cancel"
                  onClick={onClose}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="modal-submit"
                  onClick={() => void handleSubmit()}
                  disabled={submitDisabled}
                >
                  Export →
                </button>
              </div>
            </>
          ) : phase === "progress" ? (
            <div className="github-modal-progress" aria-live="polite">
              <div className="github-modal-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <div className="github-modal-progress-label">{progressLabel}</div>
            </div>
          ) : phase === "success" ? (
            <div className="github-modal-success">
              <div className="github-modal-success-icon" aria-hidden="true">
                ✓
              </div>
              <div className="github-modal-success-title">
                Exported successfully
              </div>
              {result?.repo_url && (
                <a
                  className="github-modal-success-url"
                  href={result.repo_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {result.repo_url}
                </a>
              )}
              <div className="modal-footer">
                <button
                  type="button"
                  className="modal-submit"
                  onClick={handleOpenRepo}
                >
                  Open on GitHub ↗
                </button>
              </div>
            </div>
          ) : (
            // phase === "error"
            <>
              <p className="modal-error">
                {error ?? "Export failed. Please try again."}
              </p>
              <div className="modal-footer">
                <button
                  type="button"
                  className="modal-cancel"
                  onClick={onClose}
                >
                  Close
                </button>
                <button
                  type="button"
                  className="modal-submit"
                  onClick={() => {
                    setError(null)
                    setPhase("configure")
                  }}
                >
                  Try again
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

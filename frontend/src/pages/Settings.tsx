import { useEffect, useState } from "react"
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom"

import {
  deleteGitHubIntegration,
  getGitHubIntegration,
  type GitHubIntegration,
} from "../services/api"

const RETURN_TO_KEY = "specforge:settings_return_to"

function resolveReturnTo(stateFrom: string | undefined): string {
  // Link state takes precedence (fresh click). Falls back to sessionStorage
  // so the return target survives the OAuth roundtrip. Defaults to dashboard.
  if (stateFrom && stateFrom !== "/settings") {
    sessionStorage.setItem(RETURN_TO_KEY, stateFrom)
    return stateFrom
  }
  return sessionStorage.getItem(RETURN_TO_KEY) ?? "/dashboard"
}

function backLabelFor(path: string): string {
  if (path.startsWith("/workspace/")) return "← Workspace"
  if (path === "/dashboard") return "← Dashboard"
  return "← Back"
}

export default function Settings() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()

  const stateFrom = (location.state as { from?: string } | null)?.from
  const [returnTo] = useState(() => resolveReturnTo(stateFrom))

  const [integration, setIntegration] = useState<GitHubIntegration | null>(null)
  const [disconnectConfirm, setDisconnectConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isWorking, setIsWorking] = useState(false)

  // Read the OAuth callback query params so we can surface success / error.
  const justConnected = searchParams.get("github_connected") === "true"
  const oauthError = searchParams.get("github_error")

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const result = await getGitHubIntegration()
        if (!cancelled) {
          setIntegration(result)
          setError(null)
        }
      } catch {
        if (!cancelled) {
          setError("Could not load GitHub status. Please try again.")
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [])

  // Clean the OAuth query params from the URL after we read them so a refresh
  // doesn't keep showing the same banner.
  useEffect(() => {
    if (justConnected || oauthError) {
      const cleaned = new URLSearchParams(searchParams)
      cleaned.delete("github_connected")
      cleaned.delete("github_error")
      setSearchParams(cleaned, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleConnect() {
    // Use the Vite proxy path so this routes through the backend in dev.
    window.location.href = "/api/auth/github"
  }

  function handleDisconnectClick() {
    setDisconnectConfirm(true)
    setError(null)
  }

  async function handleConfirmDisconnect() {
    setIsWorking(true)
    setError(null)
    try {
      await deleteGitHubIntegration()
      const refreshed = await getGitHubIntegration()
      setIntegration(refreshed)
      setDisconnectConfirm(false)
    } catch {
      setError("Disconnect failed. Please try again.")
    } finally {
      setIsWorking(false)
    }
  }

  function handleCancelDisconnect() {
    setDisconnectConfirm(false)
  }

  function handleBack() {
    sessionStorage.removeItem(RETURN_TO_KEY)
    navigate(returnTo)
  }

  return (
    <div className="settings-page">
      <header className="settings-header">
        <button
          type="button"
          className="settings-back-link"
          onClick={handleBack}
          aria-label={`Back to ${backLabelFor(returnTo).replace("← ", "")}`}
        >
          {backLabelFor(returnTo)}
        </button>
        <span className="settings-header-title">Settings</span>
        {/* Spacer so the title is visually centered. */}
        <span className="settings-header-spacer" aria-hidden="true" />
      </header>

      <div className="settings-content">
        <div className="settings-section-label">Integrations</div>

        <div className="settings-card">
          <div className="settings-card-info">
            <span className="settings-card-name">GitHub</span>
            <span className="settings-card-desc">
              Export workspaces to a new repo with tasks as Issues.
            </span>
          </div>

          <div className="settings-card-actions">
            {integration?.connected ? (
              disconnectConfirm ? (
                <div className="settings-disconnect-confirm">
                  <span>Remove access?</span>
                  <button
                    type="button"
                    className="settings-btn-disconnect"
                    onClick={() => void handleConfirmDisconnect()}
                    disabled={isWorking}
                  >
                    {isWorking ? "Removing…" : "Yes, disconnect"}
                  </button>
                  <Link
                    to="#"
                    className="settings-back-link"
                    onClick={(event) => {
                      event.preventDefault()
                      handleCancelDisconnect()
                    }}
                  >
                    Cancel
                  </Link>
                </div>
              ) : (
                <>
                  <span className="settings-card-status-connected">
                    <span className="settings-card-status-dot" aria-hidden="true" />
                    Connected as @{integration.github_username ?? "github-user"}
                  </span>
                  <button
                    type="button"
                    className="settings-btn-disconnect"
                    onClick={handleDisconnectClick}
                  >
                    Disconnect
                  </button>
                </>
              )
            ) : (
              <button
                type="button"
                className="settings-btn-connect"
                onClick={handleConnect}
              >
                Connect GitHub
              </button>
            )}
          </div>
        </div>

        {justConnected && integration?.connected && (
          <p className="settings-card-status-connected settings-success-banner">
            <span className="settings-card-status-dot" aria-hidden="true" />
            GitHub connected successfully.
          </p>
        )}
        {oauthError && (
          <p className="settings-error">
            GitHub authorization was cancelled or failed. Please try again.
          </p>
        )}
        {error && <p className="settings-error">{error}</p>}
      </div>
    </div>
  )
}

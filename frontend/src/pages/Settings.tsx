import { useEffect, useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router-dom"

import {
  deleteGitHubIntegration,
  getGitHubIntegration,
  type GitHubIntegration,
} from "../services/api"

const RETURN_TO_KEY = "specforge:settings_return_to"

function resolveReturnTo(stateFrom: string | undefined): string {
  if (stateFrom && stateFrom !== "/settings") {
    sessionStorage.setItem(RETURN_TO_KEY, stateFrom)
    return stateFrom
  }
  return sessionStorage.getItem(RETURN_TO_KEY) ?? "/dashboard"
}

function backLabelFor(path: string): string {
  if (path.startsWith("/workspace/")) return "Workspace"
  if (path === "/dashboard") return "Dashboard"
  return "Back"
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

  const justConnected = searchParams.get("github_connected") === "true"
  const oauthError = searchParams.get("github_error")

  useEffect(() => {
    let cancelled = false
    getGitHubIntegration()
      .then((result) => {
        if (!cancelled) {
          setIntegration(result)
          setError(null)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load GitHub status. Please try again.")
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

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

  function handleBack() {
    sessionStorage.removeItem(RETURN_TO_KEY)
    navigate(returnTo)
  }

  const connected = integration?.connected ?? false
  const username = integration?.github_username ?? null
  const backLabel = backLabelFor(returnTo)

  return (
    <div className="settings-page">
      <div className="ambient-field" aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
        <div className="ambient-band band-slate" />
      </div>

      <nav className="settings-nav">
        <div className="settings-nav-inner">
          <button
            type="button"
            className="settings-nav-back"
            onClick={handleBack}
            aria-label={`Back to ${backLabel}`}
          >
            <span aria-hidden="true">←</span>
            {backLabel}
          </button>
          <div className="settings-nav-brand">
            <span className="brand-mark brand-mark-sm">
              <span>SF</span>
            </span>
            <span className="settings-nav-divider">/</span>
            <span className="settings-nav-section">Settings</span>
          </div>
          <span className="settings-nav-spacer">spacer</span>
        </div>
      </nav>

      <main className="settings-main">
        <section className="settings-card">
          <div className="settings-hero-visual" aria-hidden="true">
            <span className="settings-hero-glow" />
            <span className="settings-hero-icon">
              <GitHubLogoLarge />
            </span>
          </div>

          <div className="settings-hero-content">
            {connected ? (
              <ConnectedView
                username={username}
                onDisconnect={handleDisconnectClick}
                disconnectConfirm={disconnectConfirm}
                onConfirm={() => void handleConfirmDisconnect()}
                onCancelConfirm={() => setDisconnectConfirm(false)}
                isWorking={isWorking}
              />
            ) : (
              <DisconnectedView onConnect={handleConnect} />
            )}

            {justConnected && connected && (
              <span className="settings-banner-success" role="status">
                <span
                  className="settings-banner-success-dot"
                  aria-hidden="true"
                />
                GitHub connected successfully.
              </span>
            )}
            {oauthError && (
              <p className="settings-error" role="alert">
                GitHub authorization was cancelled or failed. Please try again.
              </p>
            )}
            {error && (
              <p className="settings-error" role="alert">
                {error}
              </p>
            )}
          </div>
        </section>

        {!connected && (
          <section className="settings-steps" aria-label="How it works">
            <h3 className="settings-steps-heading">How it works</h3>
            <article className="settings-step">
              <span className="settings-step-number">1</span>
              <h4 className="settings-step-title">Authorize SpecForge</h4>
              <p className="settings-step-body">
                A standard GitHub OAuth screen asks you to grant access to
                your repos. The token is Fernet-encrypted at rest.
              </p>
            </article>
            <article className="settings-step">
              <span className="settings-step-number">2</span>
              <h4 className="settings-step-title">Click ↑ GitHub</h4>
              <p className="settings-step-body">
                From any finalised workspace, the new header button opens an
                export modal. Pick a repo name and visibility.
              </p>
            </article>
            <article className="settings-step">
              <span className="settings-step-number">3</span>
              <h4 className="settings-step-title">Repo + Issues created</h4>
              <p className="settings-step-body">
                We create the repo, push SPEC, PLAN, harness, and TASKS, and
                open one GitHub Issue per task. Re-export updates in place.
              </p>
            </article>
          </section>
        )}
      </main>
    </div>
  )
}

function DisconnectedView({ onConnect }: { onConnect: () => void }) {
  return (
    <>
      <span className="settings-eyebrow">✦ Integration</span>
      <h1 className="settings-hero-title">Every task, a GitHub Issue.</h1>
      <p className="settings-hero-description">
        Connect once, then push any finalised workspace to a brand-new repo
        with <strong>SPEC.md</strong>, <strong>PLAN.md</strong>, the full{" "}
        <strong>harness/</strong> directory, and one tracked Issue for every
        task — ready for a developer or coding agent to pick up.
      </p>
      <div className="settings-hero-features">
        <span className="settings-feature-pill">One Issue per T-NNN task</span>
        <span className="settings-feature-pill">Idempotent re-export</span>
        <span className="settings-feature-pill">Public or Private</span>
        <span className="settings-feature-pill">ZIP export still works</span>
      </div>
      <div className="settings-hero-actions">
        <button
          type="button"
          className="settings-hero-cta"
          onClick={onConnect}
        >
          <span className="settings-hero-cta-icon" aria-hidden="true">
            <GitHubMarkSmall />
          </span>
          Connect GitHub
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </>
  )
}

interface ConnectedViewProps {
  username: string | null
  onDisconnect: () => void
  disconnectConfirm: boolean
  onConfirm: () => void
  onCancelConfirm: () => void
  isWorking: boolean
}

function ConnectedView({
  username,
  onDisconnect,
  disconnectConfirm,
  onConfirm,
  onCancelConfirm,
  isWorking,
}: ConnectedViewProps) {
  const handle = username ?? "github-user"
  return (
    <>
      <span className="settings-eyebrow connected">✓ Connected</span>
      <h1 className="settings-hero-title">
        Linked as @{handle}.
      </h1>
      <p className="settings-hero-description">
        SpecForge will push to repos under{" "}
        <span className="settings-connected-meta-username">@{handle}</span>.
        Your token stays encrypted, used only when you trigger an export,
        and is auto-revoked if GitHub ever rejects it.
      </p>
      <div className="settings-hero-features">
        <span className="settings-feature-pill">Encrypted at rest</span>
        <span className="settings-feature-pill">Auto-revoked on 401</span>
        <span className="settings-feature-pill">No data retained on disconnect</span>
        <span className="settings-feature-pill">3 exports per hour</span>
      </div>
      <div className="settings-hero-actions">
        <a
          className="settings-hero-secondary"
          href={`https://github.com/${handle}?tab=repositories`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <GitHubMarkSmall />
          View your repos ↗
        </a>
        {disconnectConfirm ? (
          <div
            className="settings-disconnect-confirm"
            role="alertdialog"
            aria-label="Confirm disconnect"
          >
            <span className="settings-disconnect-confirm-prompt">
              Remove GitHub access?
            </span>
            <button
              type="button"
              className="settings-btn-disconnect"
              onClick={onConfirm}
              disabled={isWorking}
            >
              {isWorking ? "Removing…" : "Yes, disconnect"}
            </button>
            <button
              type="button"
              className="settings-btn-disconnect-cancel"
              onClick={onCancelConfirm}
              disabled={isWorking}
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="settings-disconnect-link"
            onClick={onDisconnect}
          >
            Disconnect →
          </button>
        )}
      </div>
    </>
  )
}

function GitHubLogoLarge() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}

function GitHubMarkSmall() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}

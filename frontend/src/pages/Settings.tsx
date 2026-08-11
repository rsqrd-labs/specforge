/**
 * Settings — hosts the GitHub App installation panel (Phase 21, T-287).
 *
 * The page shell (nav + glass card) wraps <GitHubConnection/>, which offers
 * "Install GitHub App" to a not-installed user and shows the installed account
 * and its chosen repositories once installed — the GitHub **App** model that
 * supersedes the Phase-13 OAuth token, with a one-time migration prompt for
 * legacy-OAuth users.
 */

import { useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router"

import { AiDisclaimer } from "../components/shared/AiDisclaimer"
import { BrandLogo } from "../components/shared/BrandLogo"
import DataRetentionPanel from "../components/settings/DataRetentionPanel"
import GitHubConnection from "../components/settings/GitHubConnection"
import { getGitHubIntegration } from "../services/api"

const RETURN_TO_KEY = "thought2build:settings_return_to"

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

  const stateFrom = (location.state as { from?: string } | null)?.from
  const [returnTo] = useState(() => resolveReturnTo(stateFrom))

  useEffect(() => {
    getGitHubIntegration().catch((error) => {
      console.error("[Settings] failed to load GitHub integration status:", error)
    })
  }, [])

  function handleBack() {
    sessionStorage.removeItem(RETURN_TO_KEY)
    void navigate(returnTo)
  }

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
            <BrandLogo size="small" decorative />
            <span className="settings-nav-divider">/</span>
            <span className="settings-nav-section">Settings</span>
          </div>
          <span className="settings-nav-spacer">spacer</span>
        </div>
      </nav>

      <main className="settings-main">
        <section
          className="settings-card"
          aria-label="Install the GitHub App on your account's repositories"
        >
          <div className="settings-hero-visual" aria-hidden="true">
            <span className="settings-hero-glow" />
            <span className="settings-hero-icon">
              <GitHubLogoLarge />
            </span>
          </div>

          <div className="settings-hero-content">
            <GitHubConnection />
          </div>
        </section>
        <section
          className="settings-card settings-card--plain"
          aria-label="Data retention"
        >
          <div className="settings-hero-content">
            <DataRetentionPanel />
          </div>
        </section>
        <AiDisclaimer variant="footer" className="settings-ai-disclaimer" />
      </main>
    </div>
  )
}

function GitHubLogoLarge() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}

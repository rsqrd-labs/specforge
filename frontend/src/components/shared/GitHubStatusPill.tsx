import { useEffect, useState } from "react"
import { Link, useLocation } from "react-router-dom"

import {
  getGitHubIntegration,
  type GitHubIntegration,
} from "../../services/api"
import { GitHubIcon } from "./icons"

/**
 * Header entry point that doubles as the GitHub connection-status indicator.
 *
 * Replaces the older generic gear icon. Two states:
 *
 *   not-connected → "<github-mark> Connect GitHub"  (outlined, neutral tone)
 *   connected     → "<github-mark> @username •"     (green-tinted, status dot)
 *
 * Clicking always routes to `/settings`, passing the current pathname so
 * the back arrow on the Settings page returns to the originating page.
 *
 * The pill collapses to icon-only at narrow viewport widths (≤640px).
 */
export function GitHubStatusPill() {
  const location = useLocation()
  const [integration, setIntegration] = useState<GitHubIntegration | null>(null)

  useEffect(() => {
    let cancelled = false
    getGitHubIntegration()
      .then((result) => {
        if (!cancelled) setIntegration(result)
      })
      .catch(() => {
        if (!cancelled) {
          setIntegration({ connected: false, github_username: null })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const connected = integration?.connected ?? false
  const username = integration?.github_username ?? null

  const label = connected
    ? `@${username ?? "github-user"}`
    : "Connect GitHub"
  const ariaLabel = connected
    ? `GitHub connected as @${username ?? "user"}. Manage in Settings.`
    : "Connect GitHub in Settings"
  const tooltip = connected ? "Manage GitHub connection" : "Connect GitHub"

  return (
    <Link
      to="/settings"
      state={{ from: location.pathname }}
      className={`gh-status-pill ${connected ? "connected" : "not-connected"}`}
      aria-label={ariaLabel}
      title={tooltip}
    >
      <span className="gh-status-pill-mark" aria-hidden="true">
        <GitHubIcon />
      </span>
      <span className="gh-status-pill-label">{label}</span>
      {connected && <span className="gh-status-pill-dot" aria-hidden="true" />}
    </Link>
  )
}


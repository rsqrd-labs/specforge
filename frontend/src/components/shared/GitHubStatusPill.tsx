import { useEffect, useState } from "react"
import { Link, useLocation } from "react-router-dom"

import {
  getGitHubIntegration,
  type GitHubIntegration,
} from "../../services/api"

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
        <GitHubMark />
      </span>
      <span className="gh-status-pill-label">{label}</span>
      {connected && <span className="gh-status-pill-dot" aria-hidden="true" />}
    </Link>
  )
}

function GitHubMark() {
  // GitHub Octocat mark, simplified path, currentColor for theming.
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}

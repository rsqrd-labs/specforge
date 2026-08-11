/**
 * GitHubConnection — the Settings GitHub **App install** panel (Phase 21, T-287).
 *
 * Replaces the Phase-13 OAuth "Connect GitHub" panel. The moment-of-use feeling:
 * installing a trusted tool into your own house — deliberate, transparent about
 * scope, clearly reversible.
 *
 * Layout sketch (rendered inside the Settings card hero-content):
 *
 *   [not installed]            [installed]
 *   ✦ Integration             ✓ Installed   (lotus, settled — not green)
 *   Install the GitHub App.    Installed on @org.
 *   <one slate scope line>     @org · all repositories
 *   [● Install GitHub App →]    Manage on GitHub ↗   ·   Disconnect
 *
 *   [legacy] a single slate notice sits ABOVE the panel:
 *     "You're on the old connection. Re-install the GitHub App to enable live
 *      sync."  + the same saffron install CTA.
 *
 * Visual hierarchy: the single saffron "Install GitHub App" action is the one
 * focal point, with exactly one calm slate line naming what it can touch (no
 * wall of scope checkboxes); the installed state inverts to a settled, quiet
 * lotus-tinted confirmation where the @account is the hero and Manage/Disconnect
 * are deliberately understated.
 *
 * The one delight: pressing Install morphs the button to "Opening GitHub…" with
 * a soft saffron pulse as it hands off to GitHub — a reassuring, deliberate
 * handoff, never a bare spinner.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router"

import {
  getGitHubInstallUrl,
  getGitHubInstallations,
  revokeGitHubInstallation,
} from "../../services/api"
import type { InstallationOption } from "../../types/github"
import { githubConnectionAlert } from "../../utils/errorPresentation"
import { installationManageUrl } from "../../utils/github"
import { ActionAlertPanel, type ActionAlertContent } from "../shared/ActionAlert"
import { GitHubIcon, InstalledShieldIcon } from "../shared/icons"

type PanelState = "loading" | "not_installed" | "installed" | "suspended"

function repositoryScopeLabel(selection: InstallationOption["repository_selection"]): string {
  return selection === "all" ? "all repositories" : "selected repositories"
}

export default function GitHubConnection() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [installations, setInstallations] = useState<InstallationOption[]>([])
  const [onLegacyOAuth, setOnLegacyOAuth] = useState(false)
  const [state, setState] = useState<PanelState>("loading")
  const [errorAlert, setErrorAlert] = useState<ActionAlertContent | null>(null)
  const [opening, setOpening] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)

  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const list = await getGitHubInstallations()
      if (!mounted.current) return
      setInstallations(list.installations)
      setOnLegacyOAuth(list.on_legacy_oauth)
      const active = list.installations.filter((i) => !i.suspended)
      setState(
        active.length > 0
          ? "installed"
          : list.installations.length > 0
            ? "suspended"
            : "not_installed",
      )
      setErrorAlert(null)
    } catch {
      if (!mounted.current) return
      setErrorAlert(
        githubConnectionAlert("load", {
          primaryAction: {
            label: "Try again",
            onSelect: () => {
              void refresh()
            },
            autoDismiss: false,
          },
        }),
      )
      setState("not_installed")
    }
  }, [])

  // Initial load. A `?github_installed=true` return from GitHub re-fetches the
  // freshly-created installation and then clears the param.
  useEffect(() => {
    void refresh()
    if (searchParams.get("github_installed") === "true") {
      const cleaned = new URLSearchParams(searchParams)
      cleaned.delete("github_installed")
      setSearchParams(cleaned, { replace: true })
    }
  }, [])

  async function handleInstall() {
    if (opening) return
    setOpening(true)
    setErrorAlert(null)
    try {
      const url = await getGitHubInstallUrl()
      if (url) {
        // Hand off to GitHub. The "Opening GitHub…" pulse stays visible through
        // the redirect — no spinner.
        window.location.href = url
        return
      }
      // 503 → the App isn't configured for this environment.
      setErrorAlert(
        githubConnectionAlert("not-configured", {
          primaryAction: {
            label: "Try again",
            onSelect: () => {
              void handleInstall()
            },
            autoDismiss: false,
          },
        }),
      )
    } catch {
      setErrorAlert(
        githubConnectionAlert("install", {
          primaryAction: {
            label: "Try again",
            onSelect: () => {
              void handleInstall()
            },
            autoDismiss: false,
          },
        }),
      )
    } finally {
      if (mounted.current) setOpening(false)
    }
  }

  async function handleDisconnect(id: string) {
    setRevokingId(id)
    setErrorAlert(null)
    try {
      await revokeGitHubInstallation(id)
      await refresh()
      if (mounted.current) setConfirmId(null)
    } catch {
      if (mounted.current) {
        setErrorAlert(
          githubConnectionAlert("disconnect", {
            primaryAction: {
              label: "Try again",
              onSelect: () => {
                void handleDisconnect(id)
              },
              autoDismiss: false,
            },
          }),
        )
      }
    } finally {
      if (mounted.current) setRevokingId(null)
    }
  }

  if (state === "loading") {
    return (
      <div className="settings-gh-skeleton" aria-hidden="true">
        <span className="settings-gh-skeleton-line wide" />
        <span className="settings-gh-skeleton-line" />
        <span className="settings-gh-skeleton-cta" />
      </div>
    )
  }

  const activeInstalls = installations.filter((i) => !i.suspended)

  return (
    <>
      {state !== "installed" && onLegacyOAuth && (
        <p className="settings-legacy-notice" role="note">
          <span className="settings-legacy-notice-mark" aria-hidden="true">
            <GitHubIcon />
          </span>
          You're on the old connection. Re-install the GitHub App to enable live
          sync.
        </p>
      )}

      {state === "installed" ? (
        <InstalledView
          installations={activeInstalls}
          confirmId={confirmId}
          revokingId={revokingId}
          onAskDisconnect={(id) => {
            setConfirmId(id)
            setErrorAlert(null)
          }}
          onCancelDisconnect={() => setConfirmId(null)}
          onConfirmDisconnect={(id) => void handleDisconnect(id)}
        />
      ) : (
        <NotInstalledView
          suspended={state === "suspended"}
          opening={opening}
          onInstall={() => void handleInstall()}
        />
      )}

      {errorAlert && (
        <ActionAlertPanel
          {...errorAlert}
          onDismiss={() => setErrorAlert(null)}
          className="settings-action-alert"
        />
      )}
    </>
  )
}

interface NotInstalledViewProps {
  suspended: boolean
  opening: boolean
  onInstall: () => void
}

function NotInstalledView({ suspended, opening, onInstall }: NotInstalledViewProps) {
  return (
    <>
      <span className="settings-eyebrow">✦ Integration</span>
      <h1 className="settings-hero-title">
        {suspended ? "Reconnect the GitHub App." : "Install the GitHub App."}
      </h1>
      <p className="settings-install-scope">
        {suspended
          ? "This installation is paused on GitHub. Re-install to resume live sync of issues, branches, and pull requests."
          : "Creates branches, issues, and pull requests in the repositories you choose — nothing else."}
      </p>
      <div className="settings-hero-actions">
        <button
          type="button"
          className={`settings-hero-cta${opening ? " is-opening" : ""}`}
          onClick={onInstall}
          disabled={opening}
          aria-live="polite"
        >
          <span className="settings-hero-cta-icon" aria-hidden="true">
            <GitHubIcon />
          </span>
          {opening ? "Opening GitHub…" : "Install GitHub App"}
          {!opening && <span aria-hidden="true">→</span>}
        </button>
      </div>
    </>
  )
}

interface InstalledViewProps {
  installations: InstallationOption[]
  confirmId: string | null
  revokingId: string | null
  onAskDisconnect: (id: string) => void
  onCancelDisconnect: () => void
  onConfirmDisconnect: (id: string) => void
}

function InstalledView({
  installations,
  confirmId,
  revokingId,
  onAskDisconnect,
  onCancelDisconnect,
  onConfirmDisconnect,
}: InstalledViewProps) {
  const primary = installations[0]
  return (
    <>
      <span className="settings-eyebrow installed">
        <span className="settings-eyebrow-glyph" aria-hidden="true">
          <InstalledShieldIcon />
        </span>
        Installed
      </span>
      <h1 className="settings-hero-title">
        Installed on @{primary.account_login}.
      </h1>
      <p className="settings-install-scope">
        Thought2Build can open branches, issues, and pull requests in your chosen
        repositories — and live-sync them back. Nothing else is touched.
      </p>

      <ul className="settings-install-list">
        {installations.map((install) => (
          <li key={install.id} className="settings-install-row">
            <span className="settings-install-account">
              <span className="settings-install-account-mark" aria-hidden="true">
                <GitHubIcon />
              </span>
              <span className="settings-install-account-text">
                <span className="settings-install-account-login">
                  @{install.account_login}
                </span>
                <span className="settings-install-account-repos">
                  {repositoryScopeLabel(install.repository_selection)}
                </span>
              </span>
            </span>

            <span className="settings-install-row-actions">
              <a
                className="settings-install-manage"
                href={installationManageUrl(install)}
                target="_blank"
                rel="noopener noreferrer"
              >
                Manage on GitHub
                <span aria-hidden="true"> ↗</span>
              </a>

              {confirmId === install.id ? (
                <span
                  className="settings-disconnect-confirm"
                  role="alertdialog"
                  aria-label={`Disconnect @${install.account_login}`}
                >
                  <span className="settings-disconnect-confirm-prompt">
                    Remove this installation?
                  </span>
                  <button
                    type="button"
                    className="settings-btn-disconnect"
                    onClick={() => onConfirmDisconnect(install.id)}
                    disabled={revokingId === install.id}
                  >
                    {revokingId === install.id
                      ? "Removing…"
                      : "Yes, disconnect"}
                  </button>
                  <button
                    type="button"
                    className="settings-btn-disconnect-cancel"
                    onClick={onCancelDisconnect}
                    disabled={revokingId === install.id}
                  >
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="settings-disconnect-link"
                  onClick={() => onAskDisconnect(install.id)}
                >
                  Disconnect
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </>
  )
}

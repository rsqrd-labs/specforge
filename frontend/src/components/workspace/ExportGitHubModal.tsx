/**
 * ExportGitHubModal — the mode-aware GitHub export modal (Phase 21, T-288 +
 * repo picker).
 *
 * The moment-of-use feeling: a confident fork in the road, clearly explained.
 * The user should immediately grasp "drop the files in" vs. "open a PR my agent
 * can drive green" — then watch a calm, staged hand-off rather than a frozen
 * spinner.
 *
 * Layout sketch (configure phase, rendered in the existing create-modal shell):
 *
 *   GitHub account          [ @acme-org            ▾ ]   (only when >1 install)
 *   Repository
 *     ┌───────────────────────────────────────────────┐
 *     │ [ filter repositories…                      ] │
 *     │ ◉ api-server                        Private   │
 *     │ ○ docs-site                         Public    │
 *     └───────────────────────────────────────────────┘
 *       Create a new repository instead ­/ Type a name…
 *   Export mode
 *     ◉ ⌗ Files      ○ ⤴ PR with tests
 *   N issues will be created                  [Cancel] [Export]
 *
 * Repo targeting rules (mirrors the backend exactly — see `_run_app_export`
 * and `installation_can_create_repos` in
 * backend/services/pipeline/github_export_service.py):
 *
 * - A workspace already bound to a repo (its push row has `repo_full_name`)
 *   ALWAYS re-exports there — the backend skips repo resolution entirely — so
 *   the modal shows the bound repo as a quiet locked banner instead of lying
 *   with a picker. The bound installation is pinned when still active.
 *   The banner is status-aware: a `completed` push says so outright ("Already
 *   exported" + when), `stale` explains the workspace moved on, `failed` frames
 *   the submit as a safe retry — and the CTA/issue-pill copy flips from
 *   "Export"/"created" to "Update export"/"synced", because a re-export updates
 *   files and issues in place rather than creating anything new.
 * - Unbound: pick an existing repository from the installation's list (the
 *   primary path — GitHub Apps can never create repos in personal accounts),
 *   or type a name ("manual" mode). The create-new framing appears only when
 *   the server says `can_create` (org installation on all repositories).
 * - A repo-list fetch failure is NOT an empty list: manual mode with a retry
 *   notice, so the export path is never dead-ended by a GitHub blip.
 *
 * On submit the modal becomes a staged checklist — quiet slate lines that each
 * settle with a small saffron tick as the async export (202 → poll) advances —
 * never a bare spinner, never a fake percentage.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"

import { useFocusTrap } from "../../hooks/useFocusTrap"
import {
  exportWorkspaceToGitHub,
  getApiErrorMessage,
  getGitHubInstallations,
  getGitHubPush,
  getGitHubRepositories,
} from "../../services/api"
import type {
  GitHubExportMode,
  InstallationOption,
  RepositoryOption,
} from "../../types/github"
import { installationManageUrl } from "../../utils/github"
import { ActionAlertPanel } from "../shared/ActionAlert"
import { BranchIcon, PullRequestIcon, ShippedCheckIcon } from "../shared/icons"
import { RepoPicker } from "./RepoPicker"
import { StagedProgress } from "./StagedProgress"

interface ExportGitHubModalProps {
  workspaceId: string
  workspaceName: string
  taskCount: number
  onClose: () => void
}

type Phase =
  | "loading"
  | "not_installed"
  | "configure"
  | "progress"
  | "still_working"
  | "success"
  | "error"

/** How the target repo is chosen when the workspace isn't bound yet. */
type RepoChoiceMode = "existing" | "manual"

const REPO_NAME_PATTERN = /^[a-zA-Z0-9._-]+$/
const REPO_NAME_MAX = 100

// The increment branch name is a stable backend constant
// (`_INCREMENT_BRANCH = "specforge/inc-1"`); we surface it client-side as a
// concrete preview so the PR choice feels real before submit.
const PR_BRANCH_PREVIEW = "specforge/inc-1"

/** Per-mode staged-progress lines. Each settles with a saffron tick as the
 *  async export advances; the labels advance on a gentle timer while the push is
 *  pending, but the success/fail transition is driven by the poll, not the clock. */
const MODE_STAGES: Record<GitHubExportMode, string[]> = {
  files_to_default: [
    "Queued",
    "Preparing repository",
    "Committing files & harness",
    "Opening issues",
  ],
  pr_with_tests: [
    "Queued",
    "Creating branch",
    "Scaffolding tests & CI",
    "Opening pull request",
  ],
}

const STAGE_ADVANCE_MS = 2200
const POLL_INTERVAL_MS = 1500
// Client-side timeout for the export enqueue POST. The call should resolve fast
// (it returns 202 and hands off to the worker); if the request itself hangs we
// abort via AbortController so the modal falls back to the recoverable error
// state instead of spinning forever (L-4 — T-189b).
const EXPORT_REQUEST_TIMEOUT_MS = 30_000
// After ~60s without a terminal status the export is still progressing on the
// worker; we hand off to a calm "still working" state the user can close —
// never a red error. Polling does NOT stop there: it continues at the gentler
// cadence below until a terminal status arrives, so a long export (a big task
// list means many sequential issue creates) still lands on a visible "done"
// instead of stranding the user to go verify on GitHub by hand.
const POLL_MAX_ATTEMPTS = 40
const SLOW_POLL_INTERVAL_MS = 5000

/** "Jul 12, 3:41 PM" — matches the version-history timestamp shape. */
function formatPushedAt(iso: string): string {
  const d = new Date(iso)
  return (
    d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    ", " +
    d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  )
}

function slugifyWorkspaceName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, REPO_NAME_MAX)
}

/** Client-side fallback for the create gate, used only when the repo-list
 *  fetch (whose `can_create` is authoritative — computed by the same backend
 *  helper the worker export uses) failed. Mirrors
 *  `installation_can_create_repos`. */
function fallbackCanCreate(install: InstallationOption | undefined): boolean {
  return (
    !!install &&
    install.account_type === "Organization" &&
    install.repository_selection === "all"
  )
}

export function ExportGitHubModal({
  workspaceId,
  workspaceName,
  taskCount,
  onClose,
}: ExportGitHubModalProps) {
  const navigate = useNavigate()
  const dialogRef = useRef<HTMLDivElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  useFocusTrap(dialogRef, onClose, nameInputRef)

  const [repoName, setRepoName] = useState(
    () => slugifyWorkspaceName(workspaceName) || "spec-export",
  )
  const [visibility, setVisibility] = useState<"public" | "private">("public")
  const [exportMode, setExportMode] = useState<GitHubExportMode>("files_to_default")
  const [phase, setPhase] = useState<Phase>("loading")
  // Only poll once the 202 has been accepted — otherwise the first poll can read
  // the PRIOR push row (still `completed`/`failed`/`stale` on a re-export or
  // retry) before this submit's reset-to-pending commits, and jump to a false
  // terminal state. We never poll for an operation we haven't confirmed.
  const [pollReady, setPollReady] = useState(false)
  const [installations, setInstallations] = useState<InstallationOption[]>([])
  const [installationId, setInstallationId] = useState<string | null>(null)
  // The repo this workspace's push row is already bound to. Once set, the
  // backend re-exports there unconditionally (repo resolution is skipped), so
  // the configure UI locks to it instead of offering a picker that would be
  // silently ignored.
  const [boundRepoFullName, setBoundRepoFullName] = useState<string | null>(null)
  // The prior push's outcome, read once at mount alongside the binding. This is
  // what lets the modal say "already exported" instead of presenting a bound
  // re-export as if it were a first export (the status/pushed_at were always
  // fetched — they were just dropped on the floor before).
  const [priorPush, setPriorPush] = useState<{
    status: string
    pushedAt: string | null
  } | null>(null)
  const [repos, setRepos] = useState<RepositoryOption[]>([])
  const [reposTruncated, setReposTruncated] = useState(false)
  const [canCreate, setCanCreate] = useState(false)
  const [repoChoiceMode, setRepoChoiceMode] = useState<RepoChoiceMode>("existing")
  const [selectedRepo, setSelectedRepo] = useState<RepositoryOption | null>(null)
  const [reposLoading, setReposLoading] = useState(false)
  const [repoLoadFailed, setRepoLoadFailed] = useState(false)
  const [reposReloadNonce, setReposReloadNonce] = useState(0)
  const [stageIndex, setStageIndex] = useState(0)
  const [repoUrl, setRepoUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [repoNameError, setRepoNameError] = useState<string | null>(null)
  const [notInstalledHint, setNotInstalledHint] = useState<string | null>(null)

  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  // Resolve the install identity + any existing repo binding up front. The
  // backend export requires an installation_id (App model) and 403s without
  // one; we derive readiness from the live installations list rather than the
  // legacy `isConnected` prop, which can be false for an App-only user. The
  // push read pins a bound workspace to its repo (and, when possible, its
  // installation); it is best-effort — on failure the modal degrades to the
  // unbound flow, which matches today's backend behaviour either way (a bound
  // push ignores the submitted repo name).
  useEffect(() => {
    let cancelled = false
    void (async () => {
      let list
      let push
      try {
        ;[list, push] = await Promise.all([
          getGitHubInstallations(),
          getGitHubPush(workspaceId).catch(() => null),
        ])
      } catch {
        if (cancelled) return
        setNotInstalledHint(
          "Couldn't reach GitHub. Connect the GitHub App in Settings, then try again.",
        )
        setPhase("not_installed")
        return
      }
      if (cancelled) return
      const active = list.installations.filter((i) => !i.suspended)
      if (active.length === 0) {
        setNotInstalledHint(
          list.installations.length > 0
            ? "Your GitHub App installation is suspended. Re-enable it in Settings to export."
            : "Install the GitHub App in Settings to export to a repository.",
        )
        setPhase("not_installed")
        return
      }
      const pinned =
        (push?.installation_id
          ? active.find((i) => i.id === push.installation_id)
          : undefined) ?? active[0]
      setInstallations(active)
      setInstallationId(pinned.id)
      setBoundRepoFullName(push?.repo_full_name ?? null)
      setPriorPush(
        push ? { status: push.status, pushedAt: push.pushed_at } : null,
      )
      setPhase("configure")
    })()
    return () => {
      cancelled = true
    }
  }, [workspaceId])

  // Fetch the selected installation's repo list — unbound workspaces only (a
  // bound one never consults it). Re-runs on installation switch and on the
  // Retry nonce. A failure is surfaced as manual-mode + retry, never conflated
  // with a genuinely empty list.
  useEffect(() => {
    if (installationId === null || boundRepoFullName !== null) return undefined
    let cancelled = false
    setReposLoading(true)
    setRepoLoadFailed(false)
    const currentInstallation = installations.find((i) => i.id === installationId)
    void (async () => {
      try {
        const list = await getGitHubRepositories(installationId)
        if (cancelled) return
        setRepos(list.repositories)
        setReposTruncated(list.truncated)
        setCanCreate(list.can_create)
        setSelectedRepo(null)
        setRepoChoiceMode(list.repositories.length > 0 ? "existing" : "manual")
      } catch {
        if (cancelled) return
        setRepos([])
        setReposTruncated(false)
        setCanCreate(fallbackCanCreate(currentInstallation))
        setSelectedRepo(null)
        setRepoLoadFailed(true)
        setRepoChoiceMode("manual")
      } finally {
        if (!cancelled) setReposLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [installationId, boundRepoFullName, installations, reposReloadNonce])

  const stages = MODE_STAGES[exportMode]

  // Stage-label cadence: advance on a gentle timer while in flight (the worker
  // emits no per-step events). Purely cosmetic — it never declares completion.
  useEffect(() => {
    if (phase !== "progress") return undefined
    setStageIndex(0)
    const stageTimer = window.setInterval(() => {
      // Hold at the penultimate stage until the poll confirms completion, so we
      // never show "done" before it is.
      setStageIndex((i) => Math.min(i + 1, stages.length - 1))
    }, STAGE_ADVANCE_MS)
    return () => window.clearInterval(stageTimer)
  }, [phase, stages.length])

  // The authoritative outcome: poll getGitHubPush ONLY after the 202 resolved
  // (`pollReady`), so we read this submit's push, never a stale prior one. The
  // terminal success/fail transition comes from the poll status, not the clock.
  // Past POLL_MAX_ATTEMPTS the modal softens to "still working" but polling
  // continues at the slow cadence (the phase flip re-runs this effect with the
  // new interval) — the modal must always land on a visible done/failed state
  // while it is open, however long the worker takes.
  useEffect(() => {
    if ((phase !== "progress" && phase !== "still_working") || !pollReady)
      return undefined

    let attempts = 0
    const interval =
      phase === "progress" ? POLL_INTERVAL_MS : SLOW_POLL_INTERVAL_MS
    const poll = window.setInterval(() => {
      void (async () => {
        attempts += 1
        let push
        try {
          push = await getGitHubPush(workspaceId)
        } catch {
          push = null // a transient read error is not terminal — keep polling.
        }
        if (!mounted.current) return
        if (push?.repo_url) setRepoUrl(push.repo_url)
        if (push?.status === "completed") {
          setStageIndex(stages.length)
          setPhase("success")
        } else if (push?.status === "failed") {
          setError(
            "GitHub couldn't finish this export. Re-run it, or check the repository on GitHub.",
          )
          setPhase("error")
        } else if (phase === "progress" && attempts >= POLL_MAX_ATTEMPTS) {
          setPhase("still_working")
        }
      })()
    }, interval)

    return () => window.clearInterval(poll)
  }, [phase, pollReady, workspaceId, stages.length])

  function validateRepoName(value: string): string | null {
    if (!value.trim()) return "Repo name is required."
    if (value.length > REPO_NAME_MAX) return `Maximum ${REPO_NAME_MAX} characters.`
    if (!REPO_NAME_PATTERN.test(value))
      return "Use letters, digits, '.', '_' or '-' only."
    return null
  }

  function handleRepoNameBlur() {
    setRepoNameError(validateRepoName(repoName))
  }

  /** The repo name the submit will send — bound name wins, then the picked
   *  repo, then the typed name. Empty string means "not submittable yet". */
  function resolveRepoName(): string {
    if (boundRepoFullName !== null) {
      // "owner/name" → bare name; the backend skips resolution for a bound
      // push, but the request schema still requires a well-formed repo_name.
      return boundRepoFullName.split("/")[1] ?? ""
    }
    if (repoChoiceMode === "existing") return selectedRepo?.name ?? ""
    return repoName
  }

  const handleSubmit = useCallback(async () => {
    if (boundRepoFullName === null && repoChoiceMode === "manual") {
      const validation = validateRepoName(repoName)
      if (validation) {
        setRepoNameError(validation)
        return
      }
    }
    const submitName = resolveRepoName()
    if (!submitName) return
    if (!installationId) {
      setPhase("not_installed")
      return
    }

    setError(null)
    setRepoUrl(null)
    setPollReady(false)
    setPhase("progress")

    // Bound the enqueue POST: if it hangs, abort so we surface a recoverable
    // error instead of an infinite spinner (L-4 — T-189b).
    const controller = new AbortController()
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      EXPORT_REQUEST_TIMEOUT_MS,
    )
    try {
      // 202 — the export is enqueued on the worker; we poll for the outcome.
      await exportWorkspaceToGitHub(
        workspaceId,
        {
          repo_name: submitName,
          visibility,
          installation_id: installationId,
          export_mode: exportMode,
        },
        controller.signal,
      )
      if (mounted.current) setPollReady(true)
    } catch (caught) {
      if (!mounted.current) return
      if (controller.signal.aborted) {
        // The export is idempotent (keyed by push_id), so retrying is safe.
        setError(
          "The export request timed out. Check your connection and try again.",
        )
        setPhase("error")
        return
      }
      const status =
        typeof caught === "object" && caught !== null && "response" in caught
          ? (caught as { response?: { status?: number } }).response?.status
          : undefined
      if (status === 403) {
        // Install removed/suspended between open and submit.
        setNotInstalledHint(
          "This GitHub App installation is no longer available. Reconnect it in Settings.",
        )
        setPhase("not_installed")
        return
      }
      setError(
        getApiErrorMessage(
          caught,
          "Couldn't start the export. Please try again.",
        ),
      )
      setPhase("error")
    } finally {
      window.clearTimeout(timeoutId)
    }
  }, [
    boundRepoFullName,
    repoChoiceMode,
    selectedRepo,
    repoName,
    visibility,
    exportMode,
    installationId,
    workspaceId,
  ])

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    // Block click-out only during the active staged hand-off; "still working"
    // is closable so the user can return to the workspace and watch it land.
    if (phase === "progress") return
    if (e.target === e.currentTarget) onClose()
  }

  function handleGoToSettings() {
    onClose()
    void navigate("/settings")
  }

  function handleOpenRepo() {
    if (repoUrl) window.open(repoUrl, "_blank", "noopener,noreferrer")
    onClose()
  }

  const activeInstallation = installations.find((i) => i.id === installationId)

  const submitDisabled =
    phase !== "configure" ||
    reposLoading ||
    (boundRepoFullName === null &&
      (repoChoiceMode === "existing"
        ? selectedRepo === null
        : !repoName.trim() || !!validateRepoName(repoName)))
  const closeDisabled = phase === "progress"

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
            disabled={closeDisabled}
          >
            ✕
          </button>
        </div>

        <div className="create-modal-body">
          {phase === "loading" ? (
            <div className="gh-modal-loading" aria-hidden="true">
              <span className="gh-modal-loading-line wide" />
              <span className="gh-modal-loading-line" />
            </div>
          ) : phase === "not_installed" ? (
            <div className="github-modal-not-connected">
              <p>
                {notInstalledHint ??
                  "Install the GitHub App in Settings to export to a repository."}
              </p>
              <button
                type="button"
                className="modal-submit"
                onClick={handleGoToSettings}
                aria-label="Open Settings"
              >
                Settings
              </button>
            </div>
          ) : phase === "configure" ? (
            <>
              {boundRepoFullName === null && installations.length > 1 && (
                <>
                  <label
                    className="modal-label"
                    htmlFor="github-installation-select"
                  >
                    GitHub account
                  </label>
                  <select
                    id="github-installation-select"
                    className="modal-input"
                    value={installationId ?? ""}
                    onChange={(e) => setInstallationId(e.target.value)}
                  >
                    {installations.map((install) => (
                      <option key={install.id} value={install.id}>
                        {install.account_login}
                      </option>
                    ))}
                  </select>
                </>
              )}

              <label className="modal-label" id="github-repo-section-label">
                Repository
              </label>
              {boundRepoFullName !== null ? (
                <div className="gh-bound-repo">
                  <span className="gh-bound-repo-name">{boundRepoFullName}</span>
                  {/* Status-aware notice: never present a re-export as a first
                      export. completed/stale mean "already exported" (stale
                      just adds that the workspace moved on); failed frames the
                      submit as a safe retry. */}
                  {(priorPush?.status === "completed" ||
                    priorPush?.status === "stale") && (
                    <span className="gh-bound-repo-status">
                      <ShippedCheckIcon />
                      Already exported
                      {priorPush.pushedAt
                        ? ` — ${formatPushedAt(priorPush.pushedAt)}`
                        : ""}
                    </span>
                  )}
                  <p className="gh-bound-repo-note">
                    {priorPush?.status === "completed"
                      ? "Exporting again is safe — it updates this repository's files and issues in place, never duplicates them."
                      : priorPush?.status === "stale"
                        ? "The workspace has changed since that export — export again to bring the repository up to date."
                        : priorPush?.status === "failed"
                          ? "The last export didn't finish. Exporting again retries it — anything already on GitHub is updated in place, never duplicated."
                          : priorPush?.status === "pending"
                            ? "An export is already in progress — running it again is safe; files and issues are updated in place."
                            : "This workspace is connected to this repository — exporting updates its files and issues in place."}
                  </p>
                </div>
              ) : reposLoading ? (
                <div className="gh-modal-loading" aria-hidden="true">
                  <span className="gh-modal-loading-line wide" />
                  <span className="gh-modal-loading-line" />
                </div>
              ) : repoChoiceMode === "existing" ? (
                <>
                  <RepoPicker
                    repos={repos}
                    selectedRepoId={selectedRepo?.id ?? null}
                    onSelect={setSelectedRepo}
                    truncated={reposTruncated}
                  />
                  <button
                    type="button"
                    className="gh-repo-mode-link"
                    onClick={() => setRepoChoiceMode("manual")}
                  >
                    {canCreate
                      ? "Create a new repository instead"
                      : "Type a repository name instead"}
                  </button>
                </>
              ) : (
                <>
                  {repoLoadFailed && (
                    <div className="gh-repo-notice" role="alert">
                      <span>
                        Couldn&apos;t load your repositories from GitHub. You
                        can still export by typing the repository name.
                      </span>
                      <button
                        type="button"
                        className="gh-repo-notice-retry"
                        onClick={() => setReposReloadNonce((n) => n + 1)}
                      >
                        Retry
                      </button>
                    </div>
                  )}
                  {!repoLoadFailed &&
                    repos.length === 0 &&
                    !canCreate &&
                    activeInstallation && (
                      <div className="gh-repo-notice">
                        <span>
                          This installation can&apos;t reach any repositories
                          yet.{" "}
                          <a
                            href={installationManageUrl(activeInstallation)}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Add repositories on GitHub
                          </a>
                          , then come back.
                        </span>
                        <button
                          type="button"
                          className="gh-repo-notice-retry"
                          onClick={() => setReposReloadNonce((n) => n + 1)}
                        >
                          Refresh list
                        </button>
                      </div>
                    )}
                  <input
                    ref={nameInputRef}
                    id="github-repo-name"
                    className={`modal-input${repoNameError ? " error" : ""}`}
                    type="text"
                    aria-labelledby="github-repo-section-label"
                    value={repoName}
                    onChange={(e) => {
                      setRepoName(e.target.value)
                      if (repoNameError)
                        setRepoNameError(validateRepoName(e.target.value))
                    }}
                    onBlur={handleRepoNameBlur}
                    maxLength={REPO_NAME_MAX}
                    spellCheck={false}
                    autoComplete="off"
                  />
                  {repoNameError && <p className="modal-error">{repoNameError}</p>}
                  <p className="gh-repo-manual-hint">
                    {canCreate
                      ? "Exports into this repository, creating it first if it doesn't exist yet."
                      : "Must be an existing repository this installation can access — GitHub doesn't let apps create repositories here."}
                  </p>
                  {repos.length > 0 && (
                    <button
                      type="button"
                      className="gh-repo-mode-link"
                      onClick={() => setRepoChoiceMode("existing")}
                    >
                      Choose from your repositories
                    </button>
                  )}
                </>
              )}

              {/* Visibility only matters when this export may CREATE the repo
                  (backend ignores it otherwise) — anywhere else it would be a
                  lie in the UI. */}
              {boundRepoFullName === null &&
                canCreate &&
                repoChoiceMode === "manual" && (
                  <>
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
                  </>
                )}

              <label className="modal-label" id="github-export-mode-label">
                Export mode
              </label>
              <div
                className="gh-mode-group"
                role="radiogroup"
                aria-labelledby="github-export-mode-label"
              >
                <ModeOption
                  mode="files_to_default"
                  selected={exportMode === "files_to_default"}
                  title="Files"
                  consequence="Commit the four files + harness to the default branch."
                  icon={<BranchIcon />}
                  recommended
                  onSelect={() => setExportMode("files_to_default")}
                />
                <ModeOption
                  mode="pr_with_tests"
                  selected={exportMode === "pr_with_tests"}
                  title="PR with tests"
                  consequence="Open a pull request with failing tests and CI — the repo goes green as work lands."
                  icon={<PullRequestIcon />}
                  onSelect={() => setExportMode("pr_with_tests")}
                />
              </div>

              {exportMode === "pr_with_tests" && (
                <p className="gh-branch-preview">
                  <span className="gh-branch-preview-icon" aria-hidden="true">
                    <BranchIcon />
                  </span>
                  Branch: <code>{PR_BRANCH_PREVIEW}</code>
                </p>
              )}

              {/* A bound re-export syncs issues in place (keyed by task ref);
                  only a first export creates them all. */}
              <div className="github-modal-issue-pill">
                {taskCount} issue{taskCount === 1 ? "" : "s"} will be{" "}
                {boundRepoFullName !== null ? "synced" : "created"}
              </div>

              <div className="modal-footer">
                <button type="button" className="modal-cancel" onClick={onClose}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="modal-submit"
                  onClick={() => void handleSubmit()}
                  disabled={submitDisabled}
                >
                  {boundRepoFullName !== null ? "Update export" : "Export"}
                </button>
              </div>
            </>
          ) : phase === "progress" ? (
            <StagedProgress stages={stages} stageIndex={stageIndex} />
          ) : phase === "still_working" ? (
            <div className="github-modal-not-connected">
              <p>
                Still working — a big task list means GitHub is opening issues
                one by one, which can take a few minutes. Keep this open and it
                will switch to done by itself, or close it and watch the Tasks
                stage panel.
              </p>
              <div className="modal-footer">
                {repoUrl && (
                  <button
                    type="button"
                    className="modal-cancel"
                    onClick={handleOpenRepo}
                    aria-label="Open on GitHub"
                  >
                    Open
                  </button>
                )}
                <button type="button" className="modal-submit" onClick={onClose}>
                  Done
                </button>
              </div>
            </div>
          ) : phase === "success" ? (
            <div className="github-modal-success">
              <div className="gh-success-lotus" aria-hidden="true">
                {exportMode === "pr_with_tests" ? (
                  <PullRequestIcon />
                ) : (
                  <ShippedCheckIcon />
                )}
              </div>
              <div className="github-modal-success-title">
                {exportMode === "pr_with_tests"
                  ? "Pull request opened"
                  : "Exported to GitHub"}
              </div>
              {/* The poll endpoint exposes repo_url but not a PR number, so the
                  hero links the repository; the opened PR is reachable there. */}
              {repoUrl && (
                <a
                  className="github-modal-success-url"
                  href={repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {repoUrl}
                </a>
              )}
              <div className="modal-footer">
                <button
                  type="button"
                  className="modal-submit"
                  onClick={handleOpenRepo}
                  disabled={!repoUrl}
                  aria-label="Open on GitHub"
                >
                  Open
                </button>
              </div>
            </div>
          ) : (
            // phase === "error"
            <>
              <ActionAlertPanel
                severity="error"
                title="GitHub export failed"
                message={error ?? "Export failed. Please try again."}
                recovery="Your workspace is still saved. Try again or reconnect GitHub in Settings."
                source="GitHub"
              />
              <div className="modal-footer">
                <button type="button" className="modal-cancel" onClick={onClose}>
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

interface ModeOptionProps {
  mode: GitHubExportMode
  selected: boolean
  title: string
  consequence: string
  icon: React.ReactNode
  recommended?: boolean
  onSelect: () => void
}

function ModeOption({
  selected,
  title,
  consequence,
  icon,
  recommended,
  onSelect,
}: ModeOptionProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      className={`gh-mode-option${selected ? " selected" : ""}`}
      onClick={onSelect}
    >
      <span className="gh-mode-option-head">
        <span className="gh-mode-radio" aria-hidden="true" />
        <span className="gh-mode-option-icon" aria-hidden="true">
          {icon}
        </span>
        <span className="gh-mode-option-title">{title}</span>
        {recommended && <span className="gh-mode-recommended">Recommended</span>}
      </span>
      <span className="gh-mode-option-consequence">{consequence}</span>
    </button>
  )
}

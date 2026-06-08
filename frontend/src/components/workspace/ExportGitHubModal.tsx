/**
 * ExportGitHubModal — the mode-aware GitHub export modal (Phase 21, T-288).
 *
 * The moment-of-use feeling: a confident fork in the road, clearly explained.
 * The user should immediately grasp "drop the files in" vs. "open a PR my agent
 * can drive green" — then watch a calm, staged hand-off rather than a frozen
 * spinner.
 *
 * Layout sketch (configure phase, rendered in the existing create-modal shell):
 *
 *   Repository name        [ my-spec-export            ]
 *   Visibility             [ Public ]  [ Private ]
 *   Export mode
 *     ┌───────────────────────────────────────────────┐
 *     │ ◉  ⌗  Files            (saffron ring = default) │
 *     │       Commit the four files + harness to the    │
 *     │       default branch.                           │
 *     ├───────────────────────────────────────────────┤
 *     │ ○  ⤴  PR with tests                             │
 *     │       Open a pull request with failing tests +  │
 *     │       CI — the repo goes green as work lands.    │
 *     └───────────────────────────────────────────────┘
 *        (PR selected ⇒ slides in)  ⌥ Branch: specforge/inc-1
 *   N issues will be created                  [Cancel] [Export →]
 *
 * Visual hierarchy: the segmented mode choice is the focal decision (each option
 * carries a one-line plain-language consequence, the recommended *Files* mode
 * pre-selected with a subtle saffron ring); the repo name/visibility sit above
 * it as familiar setup. On submit the modal becomes a staged checklist — quiet
 * slate lines that each settle with a small saffron tick as the async export
 * (202 → poll) advances — never a bare spinner, never a fake percentage.
 *
 * The one delight: selecting *PR with tests* slides in a concrete inline preview
 * — "Branch: specforge/inc-1" — so the abstract choice feels real before submit;
 * and a finished export gets a single one-shot lotus accent (a shipped artifact
 * is a celebration — lotus, not green).
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"

import { useFocusTrap } from "../../hooks/useFocusTrap"
import {
  exportWorkspaceToGitHub,
  getApiErrorMessage,
  getGitHubInstallations,
  getGitHubPush,
} from "../../services/api"
import type { GitHubExportMode } from "../../types/github"
import { BranchIcon, PullRequestIcon, ShippedCheckIcon } from "../shared/icons"
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
    "Creating repository",
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
// worker; we hand off to a calm "still working" state the user can close (the
// TaskCompletionPanel is where they watch it finish) — never a red error.
const POLL_MAX_ATTEMPTS = 40

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
  const [installationId, setInstallationId] = useState<string | null>(null)
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

  // Resolve the install identity up front. The backend export requires an
  // installation_id (App model) and 403s without one; we derive readiness from
  // the live installations list rather than the legacy `isConnected` prop, which
  // can be false for an App-only user. The first active installation is used;
  // managing/choosing installs lives in Settings (T-287), not here.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const list = await getGitHubInstallations()
        if (cancelled) return
        const active = list.installations.find((i) => !i.suspended)
        if (active) {
          setInstallationId(active.id)
          setPhase("configure")
        } else {
          setNotInstalledHint(
            list.installations.length > 0
              ? "Your GitHub App installation is suspended. Re-enable it in Settings to export."
              : "Install the GitHub App in Settings to export to a repository.",
          )
          setPhase("not_installed")
        }
      } catch {
        if (cancelled) return
        setNotInstalledHint(
          "Couldn't reach GitHub. Connect the GitHub App in Settings, then try again.",
        )
        setPhase("not_installed")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

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
  useEffect(() => {
    if (phase !== "progress" || !pollReady) return undefined

    let attempts = 0
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
        } else if (attempts >= POLL_MAX_ATTEMPTS) {
          setPhase("still_working")
        }
      })()
    }, POLL_INTERVAL_MS)

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

  const handleSubmit = useCallback(async () => {
    const validation = validateRepoName(repoName)
    if (validation) {
      setRepoNameError(validation)
      return
    }
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
          repo_name: repoName,
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
  }, [repoName, visibility, exportMode, installationId, workspaceId])

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    // Block click-out only during the active staged hand-off; "still working"
    // is closable so the user can return to the workspace and watch it land.
    if (phase === "progress") return
    if (e.target === e.currentTarget) onClose()
  }

  function handleGoToSettings() {
    onClose()
    navigate("/settings")
  }

  function handleOpenRepo() {
    if (repoUrl) window.open(repoUrl, "_blank", "noopener,noreferrer")
    onClose()
  }

  const submitDisabled =
    phase !== "configure" || !repoName.trim() || !!validateRepoName(repoName)
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
              >
                Open Settings →
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
                className={`modal-input${repoNameError ? " error" : ""}`}
                type="text"
                value={repoName}
                onChange={(e) => {
                  setRepoName(e.target.value)
                  if (repoNameError) setRepoNameError(validateRepoName(e.target.value))
                }}
                onBlur={handleRepoNameBlur}
                maxLength={REPO_NAME_MAX}
                spellCheck={false}
                autoComplete="off"
              />
              {repoNameError && <p className="modal-error">{repoNameError}</p>}

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

              <div className="github-modal-issue-pill">
                {taskCount} issue{taskCount === 1 ? "" : "s"} will be created
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
                  Export →
                </button>
              </div>
            </>
          ) : phase === "progress" ? (
            <StagedProgress stages={stages} stageIndex={stageIndex} />
          ) : phase === "still_working" ? (
            <div className="github-modal-not-connected">
              <p>
                Still working in the background — GitHub is finishing your export.
                You can close this; the Tasks panel will show progress as it lands.
              </p>
              <div className="modal-footer">
                {repoUrl && (
                  <button
                    type="button"
                    className="modal-cancel"
                    onClick={handleOpenRepo}
                  >
                    Open on GitHub ↗
                  </button>
                )}
                <button type="button" className="modal-submit" onClick={onClose}>
                  Got it
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

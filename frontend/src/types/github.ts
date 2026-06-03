/**
 * GitHub living-integration types (Phase 21 — T-275).
 *
 * Mirrors the backend Pydantic schemas in `backend/schemas/github.py` so the
 * client speaks the v2 (GitHub App) contract: an installation identity (not an
 * OAuth token), the `files_to_default | pr_with_tests` export modes, per-task
 * bidirectional sync state (`open | done`, closed via `pr_merge | manual`), the
 * drift signal (`out_of_sync`), and the increment timeline + idea backlog.
 *
 * These are the source of truth for the sync panel, the export modal (T-288),
 * the Settings App-install panel (T-287), and the increments timeline (T-289).
 */

// --- export modes (spec §4.14) -------------------------------------------

/** Plain file push to the default branch, or an executable PR with a red harness. */
export type GitHubExportMode = "files_to_default" | "pr_with_tests"

// --- push + per-task sync state (spec §10) -------------------------------

/** A "live" push is any non-`failed` row; `stale` is the drift/disconnect state. */
export type PushStatus = "pending" | "completed" | "failed" | "stale"

/** One task's bidirectional state: open on GitHub, or shipped (done). */
export type TaskState = "open" | "done"

/** How a task was closed — its issue's PR merged, or a manual issue close. */
export type DoneVia = "pr_merge" | "manual"

/** One task's sync row (backend `TaskSyncState`). No per-task PR url exists in
 *  the contract — the issue is the deep-link anchor; GitHub surfaces the closing
 *  PR on the issue page. */
export interface TaskSyncState {
  task_ref: string
  issue_number: number
  state: TaskState
  done_via: DoneVia | null
  done_at: string | null
  synced_at: string | null
}

/** The owner-scoped sync view for a workspace's live push (backend
 *  `SyncStateResponse`). `out_of_sync` is the drift signal: the push's source
 *  Tasks version no longer matches the workspace's current finalised Tasks. */
export interface SyncState {
  push_id: string
  status: PushStatus
  out_of_sync: boolean
  shipped: number
  total: number
  tasks: TaskSyncState[]
}

// --- App installation identity (spec §8, not an OAuth token) --------------

export type AccountType = "User" | "Organization"
export type RepositorySelection = "all" | "selected"

/** One GitHub App installation the user owns (org or personal). */
export interface InstallationOption {
  id: string
  installation_id: number
  account_login: string
  account_type: AccountType
  repository_selection: RepositorySelection
  suspended: boolean
}

/** A user may hold multiple installations; `on_legacy_oauth` is the v1→App
 *  migration signal (still holds an OAuth token, no App yet). */
export interface InstallationList {
  installations: InstallationOption[]
  on_legacy_oauth: boolean
}

/** Owner-facing summary of a user's GitHub integration status. */
export interface InstallationStatus {
  connected: boolean
  account_login: string | null
  account_type: AccountType | null
  repository_selection: RepositorySelection | null
  username: string | null
  on_legacy_oauth: boolean
}

// --- increment timeline + idea backlog (spec §10, §4.14.7) ---------------

export type IncrementStatus =
  | "draft"
  | "generating"
  | "ready"
  | "pushed"
  | "stale"

/** A versioned delta layered on the finalised workspace baseline. Increment 0
 *  is the original baseline; each subsequent `sequence` is an additive or
 *  behaviour-changing change set. */
export interface Increment {
  id: string
  workspace_id: string
  sequence: number
  title: string
  status: IncrementStatus
  baseline_version_ids: string[]
  created_at: string
  updated_at: string
}

export type IncrementIdeaSource = "user" | "github"
export type IncrementIdeaStatus = "open" | "planned" | "done" | "dismissed"

/** A lightweight backlog item — a feature captured mid-build, batched into an
 *  increment when ready. May originate in SpecForge or flow back from a GitHub
 *  issue labelled `idea`/`enhancement`. */
export interface IncrementIdea {
  id: string
  workspace_id: string
  increment_id: string | null
  source: IncrementIdeaSource
  external_ref: string | null
  text: string
  status: IncrementIdeaStatus
  created_at: string
  updated_at: string
}

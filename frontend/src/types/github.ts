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
  /** Human task identity resolved from the push's source Tasks version — the
   *  `T-NNN` number and the task heading. Both are `null` for a legacy push with
   *  no source version, or an increment task absent from the baseline; the UI
   *  then falls back to the issue number. The opaque `task_ref` is never shown. */
  human_ref: string | null
  title: string | null
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
  /** Wall-clock completion of the most recent inbound reconciliation. */
  last_inbound_sync_at: string | null
  last_inbound_sync_error: "installation_unavailable" | null
  tasks: TaskSyncState[]
}

/** Queue acknowledgement for a user-requested inbound GitHub refresh. */
export interface SyncRefreshAccepted {
  push_id: string
  requested_at: string
}

/** One row of the account-wide exports hub (`GET /integrations/github/exports`):
 *  a workspace's live GitHub export summarised for a list view — repo, lifecycle
 *  status, drift, and issue completion — without the per-task payload the
 *  per-workspace `SyncState` carries. Mirrors backend `ExportSummary`. */
export interface ExportSummary {
  workspace_id: string
  workspace_name: string
  push_id: string
  status: PushStatus
  export_mode: GitHubExportMode
  repo_full_name: string | null
  repo_url: string | null
  pr_number: number | null
  out_of_sync: boolean
  shipped: number
  total: number
  pushed_at: string | null
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

// --- repo-picker feed (backend `RepoOption` / `RepoList`) -----------------

/** One repository an installation can export into. `id` is GitHub's immutable
 *  numeric repo id; `name` is the bare name submitted as the export's
 *  `repo_name`. */
export interface RepositoryOption {
  id: number
  name: string
  full_name: string
  private: boolean
  html_url: string | null
}

/** The repo-picker feed for one installation. `can_create` is the
 *  server-computed create gate (Organization installation scoped to all
 *  repositories — the only shape GitHub Apps can create repos under);
 *  `truncated` flags that GitHub holds more repos than the capped listing
 *  returned, so the picker keeps a type-a-name escape hatch. */
export interface RepoList {
  repositories: RepositoryOption[]
  truncated: boolean
  can_create: boolean
}

// --- increment timeline + idea backlog (spec §10, §4.14.7) ---------------

export type IncrementStatus =
  | "draft"
  | "generating"
  | "ready"
  | "pushed"
  | "stale"

/** Delta generation mode. The MVP ships `additive`; `behaviour_changing`
 *  (blast-radius analysis) is gated behind a backend flag (T-279). */
export type IncrementMode = "additive" | "behaviour_changing"

/** One entry on the workspace's increment timeline — a versioned delta layered
 *  on the finalised baseline (mirrors backend `IncrementRead`). The baseline is
 *  `sequence` 0; each subsequent increment is an additive change set. */
export interface Increment {
  id: string
  sequence: number
  title: string
  status: IncrementStatus
  created_at: string
  updated_at: string
}

/** Result of `POST /increments` — the new increment plus its delta size
 *  (mirrors backend `IncrementGenerateResponse`). */
export interface IncrementGenerateResponse extends Increment {
  new_task_count: number
}

/** The 202 ack for `POST /increments/{inc_id}/push`. */
export interface IncrementPushAck {
  increment_id: string
  status: IncrementStatus
}

export type IncrementIdeaSource = "user" | "github"
export type IncrementIdeaStatus = "open" | "planned" | "done" | "dismissed"

/** A lightweight backlog item — a feature captured mid-build, batched into an
 *  increment when ready (mirrors backend `IdeaRead`). May originate in SpecForge
 *  (`source: "user"`) or flow back from a GitHub issue labelled
 *  `idea`/`enhancement` (`source: "github"`, carrying its `external_ref`). */
export interface IncrementIdea {
  id: string
  source: IncrementIdeaSource
  external_ref: string | null
  status: IncrementIdeaStatus
  text: string
  increment_id: string | null
  created_at: string
}

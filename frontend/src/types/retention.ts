import type { AIProvider } from "./workspace"

/**
 * Static data-retention policy metadata from GET /retention/policy (issue #43).
 * The delete dialog stamps `policy_version` as the ack; the Settings panel and
 * the "Recently deleted" countdown render the windows from this one source.
 */
export interface RetentionPolicy {
  policy_version: string
  trash_days: number
  legacy_archived_days: number
  stage_versions_keep: number
  stage_versions_min_age_days: number
  storyboards_keep: number
  storyboards_min_age_days: number
  cost_events_days: number
  eval_results_days: number
}

/** A trashed (archived) workspace from GET /workspaces/trashed (issue #43). */
export interface TrashedWorkspace {
  id: string
  name: string
  provider: AIProvider
  archived_at: string
  purge_after: string
  acknowledged: boolean
}

export type StageType = "spec" | "plan" | "harness" | "tasks"

export type StageStatus = "locked" | "draft" | "in_progress" | "finalised" | "stale"
export type QualityGateStatus = "clear" | "blocked" | "overridden" | "advisory"

export interface QualityGateFinding {
  kind: string
  code?: string
  severity?: string
  technology?: string
  version?: string | null
  source?: string
  evidence?: string
  detail: string
  reference: string | null
  remediation?: string
}

export interface QualityGateReason {
  code: string
  kind?: string
  severity?: string
  technology?: string
  version?: string | null
  source?: string
  evidence?: string
  detail: string
  reference: string | null
  remediation?: string
}

/** Derived, billing-honest recovery contract attached to a blocked stage's
 *  `quality_gate` by the backend (`models.stage.derive_quality_gate_recovery`).
 *  The single authoritative source for the recovery action, override
 *  availability, retry cost, refund truth, and the user-facing message. */
export interface QualityGateRecovery {
  action: string
  overridable: boolean
  credit_required: number
  refunded_prior_attempt: boolean
  message: string
}

export interface QualityGateInfo {
  stage: StageType
  kind: string | null
  findings?: QualityGateFinding[]
  missing?: string[]
  reasons?: QualityGateReason[]
  override_allowed?: boolean
  repair_attempted?: boolean
  policy_version?: string | null
  verified_at?: string | null
  sources?: string[]
  status?: QualityGateStatus
  version?: number | null
  failed_at?: string | null
  recovery?: QualityGateRecovery | null
}

export interface Stage {
  id: string
  workspace_id: string
  type: StageType
  content: string | null
  status: StageStatus
  current_version: number
  eval_result?: EvalResult | null
  finalised_at: string | null
  review_gate_acknowledged: boolean
  gap_patch_used: boolean
  quality_gate?: QualityGateInfo | null
  created_at: string
  updated_at: string
  // Honest elapsed baseline for the streaming overlay (RC-1) and the reconnect
  // operation label (A6). Both optional/nullable: absent on older backends and
  // on cache-hit drafts, in which case the overlay falls back to a pinned
  // `updated_at` baseline. `generation_started_at` is stamped once at the
  // in_progress transition and never bumped by the DB heartbeat.
  generation_started_at?: string | null
  generation_action?: string | null
}

export interface ResearchSource {
  url: string
  title: string
}

export interface StageVersion {
  id: string
  stage_id: string
  version: number
  content: string
  created_by: "user" | "ai"
  created_at: string
  /**
   * Brave web-research provenance (issue #12, Phase 4). Present only when this
   * version was generated with grounding injected; research_context being set is
   * the authoritative "this version used web research" signal. Source URLs are
   * http/https-allowlisted server-side.
   */
  research_context?: string | null
  research_sources?: ResearchSource[] | null
}

export interface EvalResult {
  id: string
  stage_version_id: string
  stage_type: StageType
  overall_score: number | null
  completeness: number | null
  clarity: number | null
  coverage_percent: number | null
  uncovered_reqs: string[] | null
  /** Requirement IDs whose harness test category was deferred under token budget
   *  (TestCategoryGap). Non-blocking — these never flag the eval — but remediable
   *  in one click via the harness free patch, so CoveragePanel surfaces them. */
  deferred_reqs?: string[] | null
  tasks_without_ref: TaskReferenceIssue[] | null
  flagged: boolean
  created_at: string
}

export interface TaskReferenceIssue {
  task_number: number
  task_title: string
  reason: string
  referenced_test?: string
  gap_type?:
    | "GENERATION_FAILURE"
    | "GENUINE_GAP"
    | "DEFERRED_COVERAGE"
    | "MISSING_PRIORITY"
    | "MISSING_ESTIMATE"
  remediation?: string
  harness_file?: string
  code_stub?: string
}

export interface GenerateResponse {
  stage_id: string
  stream_url?: string
}

export interface RefineResponse {
  diff: string
  original: string
  proposed: string
  large_selection: boolean
}

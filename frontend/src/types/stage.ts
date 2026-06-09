export type StageType = "spec" | "plan" | "harness" | "tasks"

export type StageStatus = "locked" | "draft" | "in_progress" | "finalised" | "stale"
export type QualityGateStatus = "clear" | "blocked" | "overridden"

export interface QualityGateFinding {
  kind: string
  detail: string
  reference: string | null
}

export interface QualityGateInfo {
  stage: StageType
  kind: string | null
  findings?: QualityGateFinding[]
  missing?: string[]
  status?: QualityGateStatus
  version?: number | null
  failed_at?: string | null
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
}

export interface StageVersion {
  id: string
  stage_id: string
  version: number
  content: string
  created_by: "user" | "ai"
  created_at: string
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
  tasks_without_ref: TaskReferenceIssue[] | null
  flagged: boolean
  created_at: string
}

export interface TaskReferenceIssue {
  task_number: number
  task_title: string
  reason: string
  referenced_test?: string
  gap_type?: "GENERATION_FAILURE" | "GENUINE_GAP"
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

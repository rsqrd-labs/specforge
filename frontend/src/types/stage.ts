export type StageType = "spec" | "plan" | "harness" | "tasks"

export type StageStatus = "locked" | "draft" | "in_progress" | "finalised" | "stale"

export interface Stage {
  id: string
  workspace_id: string
  type: StageType
  content: string | null
  status: StageStatus
  current_version: number
  finalised_at: string | null
  review_gate_acknowledged: boolean
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
}

export interface GenerateResponse {
  stage_id: string
  stream_url?: string
}

export interface RefineResponse {
  stage_id: string
  diff: DiffChunk[]
}

export interface DiffChunk {
  type: "add" | "remove" | "context"
  old_start?: number
  old_lines?: number
  new_start?: number
  new_lines?: number
  content: string
}

// T-USE-10 — public share types. Mirror the backend Pydantic
// PublicWorkspaceResponse (schemas/workspace.py) and the
// harness/schemas/public-workspace.schema.json contract. Adding a field
// here is also a privacy decision on the backend; keep them in lockstep.

export type PublicStageType = "spec" | "plan" | "harness" | "tasks"

export interface PublicStageView {
  type: PublicStageType
  content: string
}

export interface PublicCoverageSummary {
  tests: number
  covered: number
  total: number
  percent: number
}

export interface PublicEvalSummary {
  overall_score: number | null
  completeness: number | null
  clarity: number | null
}

export interface PublicWorkspaceResponse {
  name: string
  stages: PublicStageView[]
  coverage_summary: PublicCoverageSummary | null
  eval_summary: PublicEvalSummary | null
  shared_at: string
}

export interface ShareLinkResponse {
  slug: string
  url: string
  enabled: boolean
}

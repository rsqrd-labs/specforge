export interface CoverageSummary {
  tests: number
  covered: number
  total: number
  percent: number
}

export interface ClarificationQA {
  question: string
  answer: string
}

export interface Workspace {
  id: string
  user_id: string
  name: string
  problem_statement: string
  status: "active" | "archived"
  template_slug: string | null
  clarification_qa: ClarificationQA[] | null
  public_share_slug: string | null
  public_share_enabled: boolean
  coverage_summary: CoverageSummary | null
  created_at: string
  updated_at: string
}

export interface CreateWorkspacePayload {
  name: string
  problem_statement: string
  template_slug?: string | null
}

export interface PublicWorkspaceStage {
  type: "spec" | "plan" | "harness" | "tasks"
  content: string
}

export interface PublicWorkspaceResponse {
  name: string
  stages: PublicWorkspaceStage[]
  coverage_summary: CoverageSummary | null
  eval_summary: {
    overall_score: number | null
    completeness: number | null
    clarity: number | null
  } | null
  shared_at: string
}

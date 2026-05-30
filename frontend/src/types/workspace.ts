import type { Stage } from "./stage"

export type AIProvider = "anthropic" | "openai" | "google"
export type WorkspaceStatus = "active" | "archived"

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
  provider: AIProvider
  model: string
  status: WorkspaceStatus
  created_at: string
  updated_at: string
  template_slug?: string | null
  clarification_qa?: ClarificationQA[] | null
  public_share_slug?: string | null
  public_share_enabled?: boolean
  disable_critic?: boolean
  coverage_summary?: CoverageSummary | null
}

export interface WorkspaceWithStages extends Workspace {
  stages: Stage[]
}

export interface CreateWorkspacePayload {
  name: string
  problem_statement: string
  provider: AIProvider
  template_slug?: string | null
}

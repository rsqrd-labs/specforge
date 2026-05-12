import type { Stage } from "./stage"

export type AIProvider = "anthropic" | "openai" | "google"
export type WorkspaceStatus = "active" | "archived"

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
}

export interface WorkspaceWithStages extends Workspace {
  stages: Stage[]
}

export interface CreateWorkspacePayload {
  name: string
  problem_statement: string
  provider: AIProvider
}

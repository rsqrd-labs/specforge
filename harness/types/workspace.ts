export type AIProvider = "anthropic" | "openai" | "google"

export interface Workspace {
  id: string
  user_id: string
  name: string
  problem_statement: string
  provider: AIProvider
  model: string
  status: "active" | "archived"
  created_at: string
  updated_at: string
}

export interface CreateWorkspacePayload {
  name: string
  problem_statement: string
  provider: AIProvider
  model: string
}

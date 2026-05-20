import type { AIProvider } from "./workspace"

export type TemplateCategory =
  | "auth"
  | "payments"
  | "content"
  | "realtime"
  | "agent"
  | "tooling"

export interface Template {
  id: string
  slug: string
  name: string
  description: string
  category: TemplateCategory
  problem_statement: string
  suggested_provider: AIProvider | null
  suggested_model: string | null
  sort_order: number
  active: boolean
  created_at: string
}

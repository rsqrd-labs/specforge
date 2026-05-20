// T-USE-12 — starter template types. Mirror the backend Pydantic
// TemplateRead and harness/schemas/template.schema.json.

export type TemplateCategory =
  | "auth"
  | "payments"
  | "content"
  | "realtime"
  | "agent"
  | "tooling"

export type TemplateProvider = "anthropic" | "openai" | "google"

export interface Template {
  id: string
  slug: string
  name: string
  description: string
  category: TemplateCategory
  problem_statement: string
  suggested_provider: TemplateProvider | null
  suggested_model: string | null
  sort_order: number
  active: boolean
  created_at: string
}

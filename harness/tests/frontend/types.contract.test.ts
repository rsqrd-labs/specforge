import { describe, expectTypeOf, it } from "vitest"
import type { EvalResult, Stage, StageStatus, StageType, StageVersion } from "../../../frontend/src/types/stage"
import type { User } from "../../../frontend/src/types/user"
import type { CreateWorkspacePayload, Workspace } from "../../../frontend/src/types/workspace"

describe("shared TypeScript contracts", () => {
  it("uses the canonical stage order values", () => {
    expectTypeOf<StageType>().toEqualTypeOf<"spec" | "plan" | "harness" | "tasks">()
    expectTypeOf<StageStatus>().toEqualTypeOf<"locked" | "draft" | "in_progress" | "finalised" | "stale">()
  })

  it("matches user, workspace, stage, version, and eval data models", () => {
    expectTypeOf<User>().toMatchTypeOf<{
      id: string
      email: string
      google_id: string
      name: string | null
      avatar_url: string | null
      created_at: string
      credit_balance: number
    }>()

    expectTypeOf<CreateWorkspacePayload>().toMatchTypeOf<{
      name: string
      problem_statement: string
      provider: "anthropic" | "openai" | "google"
      model: string
    }>()

    expectTypeOf<Workspace>().toMatchTypeOf<{
      id: string
      user_id: string
      name: string
      problem_statement: string
      provider: "anthropic" | "openai" | "google"
      model: string
      status: "active" | "archived"
      created_at: string
      updated_at: string
    }>()

    expectTypeOf<Stage>().toMatchTypeOf<{
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
    }>()

    expectTypeOf<StageVersion>().toMatchTypeOf<{
      id: string
      stage_id: string
      version: number
      content: string
      created_by: "user" | "ai"
      created_at: string
    }>()

    expectTypeOf<EvalResult>().toMatchTypeOf<{
      id: string
      stage_version_id: string
      stage_type: StageType
      overall_score: number | null
      completeness: number | null
      clarity: number | null
      coverage_percent: number | null
      uncovered_reqs: string[] | null
      tasks_without_ref: unknown[] | null
      flagged: boolean
      created_at: string
    }>()
  })
})

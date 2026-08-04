import type { Stage } from "./stage"

export type WorkspaceStatus = "active" | "archived"
// Demo Day mode (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md). Default "standard"
// keeps the existing UX unchanged; "demo_day" is gated behind VITE_DEMO_DAY_MODE.
export type WorkspaceMode = "standard" | "demo_day"
export type TargetAgent = "claude_code" | "codex" | "both"

export interface CoverageSummary {
  tests: number
  covered: number
  total: number
  percent: number
}

/**
 * One construction check's outcome. Mirrors the backend `CheckResult.to_dict()`
 * in `services/pipeline/construction_checks.py`: the human-readable check name
 * (e.g. `dag_acyclic`), whether it passed, and the specific gaps when it did not.
 *
 * `advisory` checks are computed and displayed but never flip `verified`. It is
 * optional because verdicts persisted before the field existed do not carry it;
 * `constructionVerdict.ts` falls back to the legacy id set for those.
 */
/**
 * One construction check's result. Two independent flags, both optional so a
 * verdict persisted before either existed still deserialises:
 *
 * - `advisory` — never verdict-bearing *by nature* (build-time budget, task-count
 *   heuristic). Not counted as a gap anywhere.
 * - `enforced` — verdict-bearing in principle, but its backend rollout flag is
 *   still off. The gap is REAL and is still counted and shown; it just cannot
 *   withhold `verified`. Absent ⇒ treat as enforced.
 */
export interface ConstructionCheck {
  name: string
  passed: boolean
  gaps: string[]
  advisory?: boolean
  enforced?: boolean
}

/**
 * The persisted construction verdict (plan §7.2). Shape mirrors
 * `ConstructionVerdict.to_dict()` and is the same for both modes — Demo Day and
 * standard mode run different check sets behind it. `verified` is every
 * non-advisory check passing. `checks` is keyed by the check id (`C1`…).
 * `stage_versions` stamps the version of each stage the verdict ran against —
 * comparing it to the live `Stage.current_version`s is the staleness signal
 * (plan §9.2). `estimated_minutes`/`time_budget_minutes` are Demo Day's advisory
 * build-time calibration and are null in standard mode (and when no per-task
 * estimate parsed, so the UI can say "no estimate" rather than imply a 0h build).
 */
export interface ConstructionVerdict {
  verified: boolean
  checks: Record<string, ConstructionCheck>
  estimated_minutes: number | null
  time_budget_minutes: number | null
  stage_versions: Partial<Record<"spec" | "plan" | "harness" | "tasks", number>>
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
  status: WorkspaceStatus
  created_at: string
  updated_at: string
  template_slug?: string | null
  clarification_qa?: ClarificationQA[] | null
  public_share_slug?: string | null
  public_share_enabled?: boolean
  disable_critic?: boolean
  /**
   * Per-workspace opt-in for Brave web-research enrichment (issue #12).
   * Off by default; enabling it permits generation to send this workspace's
   * idea text to Brave (a third party) for up-to-date web grounding, at a
   * per-generation credit cost. Generation always works without it.
   */
  brave_research_enabled?: boolean
  /**
   * Demo Day mode profile. "standard" (the default) is the unchanged pipeline;
   * "demo_day" produces rubric-shaped artifacts plus a construction-verified
   * agent handoff bundle.
   */
  mode?: WorkspaceMode
  /** Coding-agent instruction files included in ZIP and GitHub exports. */
  target_agent?: TargetAgent | null
  /** Advisory build-time target in minutes (demo_day only; target ≤ 1440). */
  time_budget_minutes?: number | null
  /**
   * Locked-down build environment (demo_day only) — no Docker, no admin/sudo
   * installs. Set at creation for a hackathon venue that disallows installing
   * Docker/admin software.
   */
  restricted_environment?: boolean
  /**
   * Persisted construction verdict (demo_day only, plan §7.2). Null for a
   * standard workspace and until the verifier first runs after the tasks stage.
   */
  construction_verdict?: ConstructionVerdict | null
  coverage_summary?: CoverageSummary | null
}

export interface WorkspaceWithStages extends Workspace {
  stages: Stage[]
}

export interface CreateWorkspacePayload {
  name: string
  problem_statement: string
  template_slug?: string | null
  /** Demo Day mode (omit or "standard" for the default pipeline). */
  mode?: WorkspaceMode
  target_agent?: TargetAgent | null
  time_budget_minutes?: number | null
  restricted_environment?: boolean
}

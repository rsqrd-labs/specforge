import type { Stage } from "../types/stage"
import type { ConstructionVerdict } from "../types/workspace"

/**
 * Derived display state for the Demo Day construction verdict
 * (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md §7). Shared by
 * `ConstructionVerifiedBadge` and `DemoDayHandoffPanel` so the staleness logic
 * lives in exactly one place.
 *
 * - `pending`  — no verdict yet (the package is not whole / the verifier has not
 *   run). The verdict is computed off the tasks stage after all four exist.
 * - `stale`    — a stage was regenerated/refined after the verdict was stamped,
 *   so the verdict no longer describes the live package. **A stale verdict must
 *   never render as green "verified"** even if its `verified` flag is true —
 *   re-run (on export) before trusting it (plan §9.2).
 * - `verified` — C1–C4 passed and the verdict matches the live stage versions.
 * - `gaps`     — the verifier ran cleanly but found construction gaps.
 */
export type ConstructionStatus = "pending" | "stale" | "verified" | "gaps"

const STAGE_TYPES = ["spec", "plan", "harness", "tasks"] as const

/**
 * True when the verdict was computed against stage versions that no longer match
 * the live ones. Conservative: a version present on one side but not the other
 * counts as a mismatch (recompute rather than trust a possibly-wrong verdict).
 * Mirrors the backend `is_verdict_stale`.
 */
export function isVerdictStale(
  verdict: ConstructionVerdict,
  stages: Pick<Stage, "type" | "current_version">[],
): boolean {
  const live = new Map(stages.map((s) => [s.type, s.current_version]))
  return STAGE_TYPES.some(
    (type) => verdict.stage_versions[type] !== live.get(type),
  )
}

/** The construction checks that flip the verdict (C1–C4). C5/time-budget is
 *  advisory-only and is excluded from the gap count by id, matching the backend
 *  `verified = C1 and C2 and C3 and C4`. */
const VERDICT_AFFECTING_CHECKS = new Set(["C1", "C2", "C3", "C4"])

/** The list of failing verdict-affecting checks (C1–C4 only), in id order. */
export function failingChecks(
  verdict: ConstructionVerdict,
): { id: string; name: string; gaps: string[] }[] {
  return Object.entries(verdict.checks)
    .filter(([id, check]) => VERDICT_AFFECTING_CHECKS.has(id) && !check.passed)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([id, check]) => ({ id, name: check.name, gaps: check.gaps }))
}

/** The total number of named gaps across the failing verdict-affecting checks. */
export function gapCount(verdict: ConstructionVerdict): number {
  return failingChecks(verdict).reduce((sum, c) => sum + c.gaps.length, 0)
}

/** Resolve the display status, honouring staleness before `verified`. */
export function deriveConstructionStatus(
  verdict: ConstructionVerdict | null | undefined,
  stages: Pick<Stage, "type" | "current_version">[],
): ConstructionStatus {
  if (!verdict) return "pending"
  if (isVerdictStale(verdict, stages)) return "stale"
  return verdict.verified ? "verified" : "gaps"
}

/** The minimal workspace shape the verdict poller reads. */
export interface VerdictPollWorkspace {
  construction_verdict?: ConstructionVerdict | null
  stages: Pick<Stage, "type" | "current_version">[]
}

export interface VerdictPollOptions<
  W extends VerdictPollWorkspace = VerdictPollWorkspace,
> {
  /** Re-fetch the workspace (full row + stages). */
  fetchWorkspace: () => Promise<W>
  /** Apply each fetched workspace (so the badge/panel re-render as it lands).
   *  Receives the full fetched type, so callers can apply it without a cast. */
  onWorkspace: (workspace: W) => void
  /** Cooperative cancellation — a new generation / unmount flips this true. */
  isCancelled: () => boolean
  attempts?: number
  delayMs?: number
  /** Injectable for tests; defaults to a real setTimeout sleep. */
  sleep?: (ms: number) => Promise<void>
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/**
 * Bounded post-`done` poll that re-fetches the workspace until a **fresh**
 * construction verdict has landed (plan §7.3). The verdict is computed by a
 * detached background task a few seconds AFTER the tasks stream ends, so the one
 * immediate refresh is too early to see it — without this poll the badge reads
 * "pending" until a manual reload. Mirrors the async-critic post-`done` poll in
 * `useStream.ts`.
 *
 * Stops the instant a non-stale verdict is observed (the common verified path
 * settles on the first tick) or the attempt budget elapses. Fully best-effort:
 * every fetch error is swallowed; on timeout the verdict simply surfaces on the
 * next natural workspace fetch (finalise, download, navigation).
 */
export async function pollForFreshVerdict<
  W extends VerdictPollWorkspace = VerdictPollWorkspace,
>({
  fetchWorkspace,
  onWorkspace,
  isCancelled,
  attempts = 5,
  delayMs = 4000,
  sleep = defaultSleep,
}: VerdictPollOptions<W>): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await sleep(delayMs)
    if (isCancelled()) return
    try {
      const workspace = await fetchWorkspace()
      if (isCancelled()) return
      onWorkspace(workspace)
      const verdict = workspace.construction_verdict
      if (verdict && !isVerdictStale(verdict, workspace.stages)) return
    } catch {
      // Best-effort: a transient failure just means we retry or quietly time out.
    }
  }
}

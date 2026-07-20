import { describe, expect, it, vi } from "vitest"

import type { Stage, StageType } from "../types/stage"
import type { ConstructionVerdict } from "../types/workspace"
import {
  deriveConstructionStatus,
  failingChecks,
  gapCount,
  isVerdictStale,
  pollForFreshVerdict,
  type VerdictPollWorkspace,
} from "./constructionVerdict"

const STAGE_TYPES: StageType[] = ["spec", "plan", "harness", "tasks"]

function stagesAt(
  versions: Partial<Record<StageType, number>>,
): Pick<Stage, "type" | "current_version">[] {
  return STAGE_TYPES.map((type) => ({
    type,
    current_version: versions[type] ?? 1,
  }))
}

function verdict(overrides: Partial<ConstructionVerdict> = {}): ConstructionVerdict {
  return {
    verified: true,
    checks: {
      C1: { name: "dag_acyclic", passed: true, gaps: [] },
      C2: { name: "task_to_test", passed: true, gaps: [] },
      C3: { name: "ac_to_test", passed: true, gaps: [] },
      C4: { name: "e2e_reachable", passed: true, gaps: [] },
      C5: { name: "time_budget", passed: true, gaps: [] },
    },
    estimated_minutes: 240,
    time_budget_minutes: 300,
    stage_versions: { spec: 1, plan: 1, harness: 1, tasks: 1 },
    ...overrides,
  }
}

describe("isVerdictStale", () => {
  it("is fresh when every stamped version matches the live one", () => {
    expect(isVerdictStale(verdict(), stagesAt({}))).toBe(false)
  })

  it("is stale when any single stage moved past the stamp", () => {
    expect(isVerdictStale(verdict(), stagesAt({ harness: 2 }))).toBe(true)
  })

  it("is stale when a stamped version is missing entirely", () => {
    const v = verdict({ stage_versions: { spec: 1, plan: 1, harness: 1 } })
    expect(isVerdictStale(v, stagesAt({}))).toBe(true)
  })
})

describe("failingChecks / gapCount", () => {
  it("counts only the verdict-affecting C1–C4 gaps, never advisory C5", () => {
    const v = verdict({
      verified: false,
      checks: {
        C1: { name: "dag_acyclic", passed: true, gaps: [] },
        C2: { name: "task_to_test", passed: false, gaps: ["g1"] },
        C3: { name: "ac_to_test", passed: false, gaps: ["g2", "g3"] },
        C4: { name: "e2e_reachable", passed: true, gaps: [] },
        C5: { name: "time_budget", passed: false, gaps: ["over budget", "x"] },
      },
    })
    expect(failingChecks(v).map((c) => c.id)).toEqual(["C2", "C3"])
    expect(gapCount(v)).toBe(3)
  })
})

describe("deriveConstructionStatus", () => {
  it("returns pending when there is no verdict", () => {
    expect(deriveConstructionStatus(null, stagesAt({}))).toBe("pending")
  })

  it("returns verified for a fresh, passing verdict", () => {
    expect(deriveConstructionStatus(verdict(), stagesAt({}))).toBe("verified")
  })

  it("returns gaps for a fresh, failing verdict", () => {
    expect(
      deriveConstructionStatus(verdict({ verified: false }), stagesAt({})),
    ).toBe("gaps")
  })

  it("returns stale before verified — never a false green after a refine", () => {
    // verified is true, but a downstream stage moved → must read as stale.
    expect(deriveConstructionStatus(verdict(), stagesAt({ tasks: 3 }))).toBe(
      "stale",
    )
  })
})

describe("pollForFreshVerdict", () => {
  // No-op sleep so the bounded poll resolves synchronously in tests.
  const noSleep = () => Promise.resolve()

  function workspace(
    overrides: Partial<VerdictPollWorkspace> = {},
  ): VerdictPollWorkspace {
    return { construction_verdict: null, stages: stagesAt({}), ...overrides }
  }

  it("stops the instant a fresh verdict lands and applies each fetch", async () => {
    // First tick: still pending; second tick: a fresh (non-stale) verdict.
    const fetchWorkspace = vi
      .fn()
      .mockResolvedValueOnce(workspace())
      .mockResolvedValueOnce(workspace({ construction_verdict: verdict() }))
    const onWorkspace = vi.fn()

    await pollForFreshVerdict({
      fetchWorkspace,
      onWorkspace,
      isCancelled: () => false,
      attempts: 5,
      sleep: noSleep,
    })

    // Stopped on the 2nd attempt — never burned the remaining budget.
    expect(fetchWorkspace).toHaveBeenCalledTimes(2)
    expect(onWorkspace).toHaveBeenCalledTimes(2)
  })

  it("keeps polling while the verdict is stale, never settling on it", async () => {
    // A verified-but-stale verdict (a stage moved past the stamp) must not stop
    // the poll — it would otherwise surface a false green.
    const staleWs = workspace({
      construction_verdict: verdict(),
      stages: stagesAt({ tasks: 2 }),
    })
    const fetchWorkspace = vi.fn().mockResolvedValue(staleWs)

    await pollForFreshVerdict({
      fetchWorkspace,
      onWorkspace: vi.fn(),
      isCancelled: () => false,
      attempts: 3,
      sleep: noSleep,
    })

    expect(fetchWorkspace).toHaveBeenCalledTimes(3) // ran the full budget
  })

  it("respects cancellation — never fetches once cancelled", async () => {
    const fetchWorkspace = vi.fn().mockResolvedValue(workspace())

    await pollForFreshVerdict({
      fetchWorkspace,
      onWorkspace: vi.fn(),
      isCancelled: () => true, // cancelled before the first fetch
      attempts: 5,
      sleep: noSleep,
    })

    expect(fetchWorkspace).not.toHaveBeenCalled()
  })

  it("times out cleanly when fetches keep failing — never throws", async () => {
    const fetchWorkspace = vi.fn().mockRejectedValue(new Error("network"))
    const onWorkspace = vi.fn()

    await expect(
      pollForFreshVerdict({
        fetchWorkspace,
        onWorkspace,
        isCancelled: () => false,
        attempts: 3,
        sleep: noSleep,
      }),
    ).resolves.toBeUndefined()

    expect(fetchWorkspace).toHaveBeenCalledTimes(3)
    expect(onWorkspace).not.toHaveBeenCalled()
  })
})

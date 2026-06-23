import { describe, expect, it } from "vitest"

import type { Stage } from "../types/stage"
import { pickActiveStageOnLoad } from "./Workspace"

function makeStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "spec",
    content: null,
    status: "draft",
    current_version: 0,
    eval_result: null,
    finalised_at: null,
    gap_patch_used: false,
    review_gate_acknowledged: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

// Refresh-during-generation: which stage the workspace selects on (re)load
// (docs/REFRESH_DURING_GENERATION_PLAN.md). The in-progress stage must win on a
// fresh mount so its reconnect overlay is visible — across every stage.
describe("pickActiveStageOnLoad", () => {
  it("keeps a still-valid existing selection", () => {
    const stages = [
      makeStage({ id: "s1", type: "spec", status: "finalised" }),
      makeStage({ id: "s2", type: "plan", status: "in_progress" }),
    ]
    expect(pickActiveStageOnLoad(stages, "s1")).toBe("s1")
  })

  it("drops a stale selection that no longer exists", () => {
    const stages = [makeStage({ id: "s1", type: "spec", status: "draft" })]
    expect(pickActiveStageOnLoad(stages, "gone")).toBe("s1")
  })

  it.each(["spec", "plan", "harness", "tasks"] as const)(
    "lands on the in-progress %s after a fresh mount instead of the first unlocked stage",
    (type) => {
      const stages = [
        makeStage({ id: "spec", type: "spec", status: "finalised" }),
        makeStage({ id: "plan", type: "plan", status: "finalised" }),
        makeStage({ id: "harness", type: "harness", status: "finalised" }),
        makeStage({ id: "tasks", type: "tasks", status: "finalised" }),
      ].map((stage) =>
        stage.type === type ? { ...stage, status: "in_progress" as const } : stage,
      )
      // No prior selection (fresh mount, e.g. a refresh): the generating stage wins.
      expect(pickActiveStageOnLoad(stages, null)).toBe(type)
    },
  )

  it("falls back to the first unlocked stage when nothing is generating", () => {
    const stages = [
      makeStage({ id: "spec", type: "spec", status: "finalised" }),
      makeStage({ id: "plan", type: "plan", status: "draft" }),
      makeStage({ id: "harness", type: "harness", status: "locked" }),
    ]
    expect(pickActiveStageOnLoad(stages, null)).toBe("spec")
  })

  it("returns null when there are no stages", () => {
    expect(pickActiveStageOnLoad([], null)).toBeNull()
  })
})

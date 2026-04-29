import { describe, expect, it } from "vitest"
import { useStageStore } from "../../../frontend/src/store/stageStore"

describe("stage store contract", () => {
  it("appends streaming tokens without replacing prior content", () => {
    useStageStore.setState({
      streamingContent: "",
      isStreaming: true,
      activeStage: "spec",
      lastSyncedLength: 0,
    })

    useStageStore.getState().appendStreamToken("hello")
    useStageStore.getState().appendStreamToken(" world")

    expect(useStageStore.getState().streamingContent).toBe("hello world")
  })

  it("marks downstream stages stale from the edited stage", () => {
    useStageStore.setState({
      stages: {
        spec: stage("spec", "finalised"),
        plan: stage("plan", "finalised"),
        harness: stage("harness", "finalised"),
        tasks: stage("tasks", "finalised"),
      },
    })

    useStageStore.getState().markStale("plan")

    expect(useStageStore.getState().stages.spec.status).toBe("finalised")
    expect(useStageStore.getState().stages.plan.status).toBe("finalised")
    expect(useStageStore.getState().stages.harness.status).toBe("stale")
    expect(useStageStore.getState().stages.tasks.status).toBe("stale")
  })
})

function stage(
  type: "spec" | "plan" | "harness" | "tasks",
  status: "locked" | "draft" | "in_progress" | "finalised" | "stale",
) {
  return {
    id: `${type}-id`,
    workspace_id: "workspace-id",
    type,
    content: "",
    status,
    current_version: 1,
    finalised_at: null,
    review_gate_acknowledged: false,
    created_at: "2026-04-25T00:00:00Z",
    updated_at: "2026-04-25T00:00:00Z",
  }
}

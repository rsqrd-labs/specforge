import { describe, expect, it } from "vitest"

import type { Stage, StageType } from "../types/stage"
import type { StoryboardDetail, StoryboardDownloadKind } from "../types/storyboard"
import {
  firstUnlockedStage, formatStageStatus, getGenerationActionLabel,
  getWorkspaceGenerationLock, getWorkspaceGenerationVerb, pickActiveStageOnLoad,
  previousStageType, reconnectOperation, sortStages, storyboardFileStem,
  storyboardFilename,
} from "./Workspace"

const stage = (type: StageType, status: Stage["status"] = "draft"): Stage => ({
  id: `stage-${type}`, workspace_id: "ws", type, status, content: "", current_version: 0,
  finalised_at: null, review_gate_acknowledged: false, gap_patch_used: false,
  created_at: "", updated_at: "",
})

describe("Workspace decision helpers", () => {
  it.each([
    ["focused-patch", "Preparing refinement"],
    ["quality-gate-regenerate", "Regenerating with gate feedback"],
    ["regenerate-gaps", "Regenerating coverage gaps"],
    ["regenerate", "Regenerating stage"],
    ["generate", "Generating stage"],
  ] as const)("labels %s", (operation, label) => {
    expect(getGenerationActionLabel(operation)).toBe(label)
  })

  it("normalizes reconnect actions and stage order", () => {
    expect(reconnectOperation("regenerate")).toBe("regenerate")
    expect(reconnectOperation("unexpected")).toBe("generate")
    expect(reconnectOperation(null)).toBe("generate")
    const stages = [stage("tasks"), stage("spec"), stage("harness"), stage("plan")]
    expect(sortStages(stages).map((item) => item.type)).toEqual(["spec", "plan", "harness", "tasks"])
    expect(stages[0].type).toBe("tasks")
  })

  it("selects an existing, generating, or first unlocked stage", () => {
    const stages = [stage("spec", "locked"), stage("plan", "in_progress"), stage("harness")]
    expect(pickActiveStageOnLoad(stages, "stage-harness")).toBe("stage-harness")
    expect(pickActiveStageOnLoad(stages, "missing")).toBe("stage-plan")
    expect(firstUnlockedStage([stage("spec", "locked"), stage("plan")])?.type).toBe("plan")
    expect(firstUnlockedStage([stage("spec", "locked")])).toBeNull()
    expect(pickActiveStageOnLoad([], null)).toBeNull()
  })

  it("formats stage and generation state", () => {
    expect(previousStageType("spec")).toBe("spec")
    expect(previousStageType("tasks")).toBe("harness")
    expect(formatStageStatus("in_progress")).toBe("in progress")
    expect(getWorkspaceGenerationVerb("focused-patch")).toBe("Refining")
    expect(getWorkspaceGenerationVerb("regenerate")).toBe("Regenerating")
    expect(getWorkspaceGenerationVerb("regenerate-gaps")).toBe("Regenerating")
    expect(getWorkspaceGenerationVerb("quality-gate-regenerate")).toBe("Regenerating")
    expect(getWorkspaceGenerationVerb(null)).toBe("Generating")
    expect(getWorkspaceGenerationLock(false, null, null)).toMatchObject({ locked: false, stageLabel: null })
    expect(getWorkspaceGenerationLock(true, stage("plan"), "focused-patch")).toMatchObject({
      message: "Refining PLAN", stageLabel: "PLAN",
    })
    expect(getWorkspaceGenerationLock(true, null, null).message).toBe("Generating workspace")
  })

  it.each(["html", "pdf", "notes", "demo-script", "appendix"] as StoryboardDownloadKind[])(
    "builds a safe %s storyboard filename",
    (kind) => {
      const storyboard = { id: "id-7", title: " My Demo / Story! " } as StoryboardDetail
      expect(storyboardFilename(storyboard, kind)).toMatch(/^thought2build-my-demo-story-/)
    },
  )

  it("falls back when a storyboard title has no safe characters", () => {
    expect(storyboardFileStem("***", "42")).toBe("storyboard-42")
    expect(storyboardFileStem("A".repeat(80), "42")).toHaveLength(60)
  })
})

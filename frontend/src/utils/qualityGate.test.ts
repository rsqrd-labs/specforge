import { describe, expect, it } from "vitest"

import type { QualityGateInfo, Stage, StageType } from "../types/stage"
import { deriveFinaliseGateBlock, gateFallbackMessage } from "./qualityGate"

function makeStage(quality_gate?: QualityGateInfo | null): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "spec",
    content: "partial",
    status: "draft",
    current_version: 2,
    eval_result: null,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    quality_gate: quality_gate ?? null,
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
  }
}

function blockedGate(
  kind: string,
  recoveryMessage?: string,
): QualityGateInfo {
  return {
    stage: "spec" as StageType,
    kind,
    status: "blocked",
    recovery: recoveryMessage
      ? {
          action: "regenerate",
          overridable: kind === "missing_sections" || kind === "critic_findings",
          credit_required: 10,
          refunded_prior_attempt: kind === "incomplete_output",
          message: recoveryMessage,
        }
      : null,
  }
}

describe("deriveFinaliseGateBlock", () => {
  it("is not blocked when there is no quality gate", () => {
    expect(deriveFinaliseGateBlock(makeStage(null))).toEqual({
      blocked: false,
      message: "Regenerate or override the quality gate before finalising",
    })
  })

  it("is not blocked when the gate is clear/overridden, not blocked", () => {
    const stage = makeStage({ stage: "spec", kind: null, status: "overridden" })
    expect(deriveFinaliseGateBlock(stage).blocked).toBe(false)
  })

  it("handles a null/undefined stage without throwing", () => {
    expect(deriveFinaliseGateBlock(null).blocked).toBe(false)
    expect(deriveFinaliseGateBlock(undefined).blocked).toBe(false)
  })

  it("surfaces the backend recovery message verbatim when blocked", () => {
    // "after refetch": given a persisted stage object with status=blocked, the
    // disable derives blocked=true and shows the backend's authoritative copy.
    const message =
      "This version stopped before it was complete and can't be finalised. " +
      "Regenerate to produce a full version. Your previous attempt was refunded."
    const result = deriveFinaliseGateBlock(
      makeStage(blockedGate("incomplete_output", message)),
    )
    expect(result).toEqual({ blocked: true, message })
  })

  // The guardrail: regression coverage across ALL gate kinds, not just the repro.
  it.each([
    ["incomplete_output", "Regenerate a complete version before finalising"],
    [
      "technology_safety",
      "Regenerate with supported technology choices before finalising",
    ],
    ["missing_sections", "Regenerate or override the quality gate before finalising"],
    ["critic_findings", "Regenerate or override the quality gate before finalising"],
  ])(
    "falls back to kind-specific copy for %s when recovery is absent",
    (kind, expected) => {
      const result = deriveFinaliseGateBlock(makeStage(blockedGate(kind)))
      expect(result).toEqual({ blocked: true, message: expected })
    },
  )
})

describe("gateFallbackMessage", () => {
  it("covers known kinds and an unknown/forward-compatible default", () => {
    expect(gateFallbackMessage("incomplete_output")).toMatch(/complete version/)
    expect(gateFallbackMessage("technology_safety")).toMatch(/supported technology/)
    expect(gateFallbackMessage("missing_sections")).toMatch(/override/)
    expect(gateFallbackMessage(undefined)).toMatch(/override/)
  })
})

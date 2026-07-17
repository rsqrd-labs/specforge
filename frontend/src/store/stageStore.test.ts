import { beforeEach, describe, expect, it } from "vitest"
import type { Stage } from "../types/stage"
import { useStageStore } from "./stageStore"

function makeStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "s1",
    workspace_id: "ws",
    type: "spec",
    content: null,
    status: "in_progress",
    current_version: 1,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    created_at: "",
    updated_at: "",
    ...overrides,
  }
}

function resetStore() {
  useStageStore.setState({
    stages: {},
    streamingContent: {},
    activeStream: null,
    qualityGate: {},
    streamProgress: {},
    pendingReset: {},
  })
}

describe("stageStore stream_reset (deferred reset)", () => {
  beforeEach(resetStore)

  it("keeps the live draft visible after a reset until the first replacement token", () => {
    const store = useStageStore.getState()
    store.startStream("s1")
    store.appendToken("s1", "# Spec\n\npartial draft that got")

    // stream_reset fires mid-generation (completion repair / canonical replay).
    store.clearStreamContent("s1")

    // The draft must NOT blank — otherwise hasLiveDraft flips false and the
    // overlay regresses to the full from-scratch loading card during a repair.
    expect(useStageStore.getState().streamingContent["s1"]).toBe(
      "# Spec\n\npartial draft that got",
    )
    expect(useStageStore.getState().pendingReset["s1"]).toBe(true)
  })

  it("overwrites (not appends) the stale buffer on the first token after a reset", () => {
    const store = useStageStore.getState()
    store.startStream("s1")
    store.appendToken("s1", "stale partial")
    store.clearStreamContent("s1")

    store.appendToken("s1", "# Final")
    store.appendToken("s1", " artifact")

    expect(useStageStore.getState().streamingContent["s1"]).toBe("# Final artifact")
    expect(useStageStore.getState().pendingReset["s1"]).toBeUndefined()
  })

  it("appends normally when no reset is pending", () => {
    const store = useStageStore.getState()
    store.startStream("s1")
    store.appendToken("s1", "a")
    store.appendToken("s1", "b")
    expect(useStageStore.getState().streamingContent["s1"]).toBe("ab")
  })

  it("clears the pending-reset flag on a fresh stream and on finalise", () => {
    const store = useStageStore.getState()
    store.startStream("s1")
    store.appendToken("s1", "draft")
    store.clearStreamContent("s1")
    expect(useStageStore.getState().pendingReset["s1"]).toBe(true)

    store.startStream("s1")
    expect(useStageStore.getState().pendingReset["s1"]).toBeUndefined()

    store.appendToken("s1", "draft")
    store.clearStreamContent("s1")
    store.finaliseStream("s1")
    expect(useStageStore.getState().pendingReset["s1"]).toBeUndefined()
  })
})

describe("stageStore discardStream", () => {
  beforeEach(resetStore)

  it("drops the orphaned client buffer WITHOUT persisting it into the stage", () => {
    const store = useStageStore.getState()
    store.startStream("s1")
    store.appendToken("s1", "partial draft that was streaming")
    store.setStreamProgress("s1", {
      stage: "harness",
      state: "streaming",
      elapsed_seconds: 3,
    })

    store.discardStream("s1")

    const state = useStageStore.getState()
    expect(state.streamingContent["s1"]).toBeUndefined()
    expect(state.streamProgress["s1"]).toBeUndefined()
    expect(state.pendingReset["s1"]).toBeUndefined()
    expect(state.activeStream).toBeNull()
    // Critically: the partial must NOT be written into a stage's content —
    // the reconnect poll owns delivering the final artifact.
    expect(state.stages["s1"]).toBeUndefined()
  })

  it("leaves a different stage's active stream untouched", () => {
    const store = useStageStore.getState()
    store.startStream("s2")
    store.appendToken("s2", "other stage")

    store.discardStream("s1")

    const state = useStageStore.getState()
    expect(state.activeStream).toBe("s2")
    expect(state.streamingContent["s2"]).toBe("other stage")
  })
})

describe("stageStore finaliseStream empty-buffer guard (A3)", () => {
  beforeEach(resetStore)

  it("keeps prior content when the stream errored before its first token", () => {
    const store = useStageStore.getState()
    store.setStage(makeStage({ content: "# Existing draft" }))
    // startStream seeds streamingContent["s1"] = "" — an empty string, which is
    // NOT nullish. `?? existing.content` would let it blank the editor; the fix
    // uses `|| existing.content`.
    store.startStream("s1")

    store.finaliseStream("s1")

    expect(useStageStore.getState().stages["s1"].content).toBe("# Existing draft")
  })

  it("commits the accumulated buffer when tokens actually streamed", () => {
    const store = useStageStore.getState()
    store.setStage(makeStage({ content: "old content" }))
    store.startStream("s1")
    store.appendToken("s1", "# New content")

    store.finaliseStream("s1")

    expect(useStageStore.getState().stages["s1"].content).toBe("# New content")
  })
})

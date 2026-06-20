import { beforeEach, describe, expect, it } from "vitest"
import { useStageStore } from "./stageStore"

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

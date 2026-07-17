import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { Stage } from "../types/stage"

// The reconcile matrix (P0-A): after an interrupted stream, useStream never
// re-POSTs — it refetches once and uses the version bump to decide the outcome.

vi.mock("../services/api", () => ({
  generateStage: vi.fn(async (id: string) => ({
    stage_id: id,
    stream_url: `/stages/${id}/generate`,
  })),
  regenerateStage: vi.fn(async (id: string) => ({
    stage_id: id,
    stream_url: `/stages/${id}/regenerate`,
  })),
  regenerateStageForGaps: vi.fn(async (id: string) => ({
    stage_id: id,
    stream_url: `/stages/${id}/regenerate-gaps`,
  })),
  getStage: vi.fn(),
}))

vi.mock("../services/sseService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/sseService")>()
  return { ...actual, createSSEConnection: vi.fn() }
})

import { getStage } from "../services/api"
import { StreamError, createSSEConnection } from "../services/sseService"
import { useStageStore } from "../store/stageStore"
import { useStream } from "./useStream"

const mockGetStage = vi.mocked(getStage)
const mockCreateSSE = vi.mocked(createSSEConnection)

function makeStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "s1",
    workspace_id: "ws",
    type: "spec",
    content: "# Original",
    status: "draft",
    current_version: 1,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    created_at: "",
    updated_at: "",
    ...overrides,
  }
}

/** Make the SSE connection settle by immediately firing `onError(code)`. */
function sseErrors(code: string) {
  mockCreateSSE.mockImplementation((opts) => {
    opts.onError(new StreamError(code, `mock ${code}`))
    return { close: vi.fn() }
  })
}

/** Make the SSE connection settle by immediately firing `onDone`. */
function sseDone(stageId: string) {
  mockCreateSSE.mockImplementation((opts) => {
    opts.onDone(stageId)
    return { close: vi.fn() }
  })
}

describe("useStream stream_interrupted reconcile (P0-A)", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockGetStage.mockReset()
    mockCreateSSE.mockReset()
    useStageStore.setState({
      stages: { s1: makeStage() },
      streamingContent: {},
      activeStream: null,
      qualityGate: {},
      streamProgress: {},
      pendingReset: {},
    })
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it("hands off to reconnect when the refetch shows the stage still in_progress", async () => {
    sseErrors("stream_interrupted")
    mockGetStage.mockResolvedValue(makeStage({ status: "in_progress" }))

    const { result } = renderHook(() => useStream("s1"))
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.start("generate")
    })

    expect(outcome).toBeNull()
    expect(result.current.error).toBeNull() // silent hand-off, no alert
    expect(useStageStore.getState().stages.s1.status).toBe("in_progress")
    expect(mockGetStage).toHaveBeenCalledTimes(1) // reconcile refetch only
  })

  it("treats a bumped version as done (work landed) — never re-POSTs", async () => {
    sseErrors("stream_interrupted")
    mockGetStage.mockResolvedValue(
      makeStage({ status: "draft", current_version: 2, content: "# Delivered" }),
    )

    const { result } = renderHook(() => useStream("s1"))
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.start("generate")
    })

    expect(outcome).not.toBeNull()
    expect(result.current.error).toBeNull()
    expect(useStageStore.getState().stages.s1.current_version).toBe(2)
    expect(useStageStore.getState().stages.s1.content).toBe("# Delivered")
  })

  it("offers a user-consented retry when the version is unchanged (failed + refunded)", async () => {
    sseErrors("stream_interrupted")
    mockGetStage.mockResolvedValue(makeStage({ status: "draft", current_version: 1 }))

    const { result } = renderHook(() => useStream("s1"))
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.start("generate")
    })

    expect(outcome).toBeNull()
    // Retryable error surfaced — but no automatic re-POST ever happened.
    expect(result.current.error?.code).toBe("stream_interrupted")
  })

  it("generation_in_progress reconciles into the reconnect UX (no alert)", async () => {
    sseErrors("generation_in_progress")
    mockGetStage.mockResolvedValue(makeStage({ status: "in_progress" }))

    const { result } = renderHook(() => useStream("s1"))
    await act(async () => {
      await result.current.start("generate")
    })

    expect(result.current.error).toBeNull()
    expect(useStageStore.getState().stages.s1.status).toBe("in_progress")
  })

  it("A2: a post-done refetch failure does NOT regress content or raise an error", async () => {
    sseDone("s1")
    mockGetStage.mockRejectedValue(new Error("network"))

    const { result } = renderHook(() => useStream("s1"))
    let outcome: unknown
    await act(async () => {
      outcome = await result.current.start("generate")
    })

    // Self-heals via the reconnect poll — no error, no revert to pre-gen content.
    expect(outcome).toBeNull()
    expect(result.current.error).toBeNull()
    expect(useStageStore.getState().stages.s1.content).toBe("# Original")
  })

  it("A2: drops the orphaned streamed buffer + activeStream (nit b)", async () => {
    sseDone("s1")
    mockGetStage.mockRejectedValue(new Error("network"))
    // Seed a streamed buffer + activeStream as an in-flight stream would.
    useStageStore.setState({
      streamingContent: { s1: "# partial" },
      activeStream: "s1",
    })

    const { result } = renderHook(() => useStream("s1"))
    await act(async () => {
      await result.current.start("generate")
    })

    // runDoneTail threw at getStage before its own discard; the A2 catch must
    // still clear the buffer so it can't leak / re-hydrate over the real draft.
    expect(useStageStore.getState().streamingContent.s1).toBeUndefined()
    expect(useStageStore.getState().activeStream).toBeNull()
  })

  it("#5: the optimistic in_progress flip strips the prior run's start stamp", async () => {
    // Never settles — we inspect the optimistic store state mid-stream.
    mockCreateSSE.mockImplementation(() => ({ close: vi.fn() }))
    useStageStore.setState({
      stages: {
        s1: makeStage({
          generation_started_at: "2020-01-01T00:00:00Z", // a stale, ancient start
          generation_action: "regenerate",
        }),
      },
    })

    const { result } = renderHook(() => useStream("s1"))
    act(() => {
      void result.current.start("generate")
    })

    const s1 = useStageStore.getState().stages.s1
    expect(s1.status).toBe("in_progress")
    // The prior run's stamps must NOT ride along, or the overlay computes elapsed
    // from 2020 and shows a wildly wrong time until the server supplies the real
    // start.
    expect(s1.generation_started_at).toBeNull()
    expect(s1.generation_action).toBeNull()
  })

  it("#3b: clears a stale error when the active stage changes", async () => {
    // A failed generation on s1 leaves a retryable error.
    sseErrors("stream_interrupted")
    mockGetStage.mockResolvedValue(makeStage({ status: "draft", current_version: 1 }))

    const { result, rerender } = renderHook(({ id }) => useStream(id), {
      initialProps: { id: "s1" as string | null },
    })
    await act(async () => {
      await result.current.start("generate")
    })
    expect(result.current.error?.code).toBe("stream_interrupted")

    // Navigating to a different stage must not carry s1's error onto s2 (where a
    // "Try again" would charge s2).
    act(() => {
      rerender({ id: "s2" })
    })
    expect(result.current.error).toBeNull()
  })
})

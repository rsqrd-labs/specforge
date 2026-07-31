import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { Stage } from "../types/stage"

// The reconcile matrix (P0-A): after an interrupted stream, useStream never
// re-POSTs — it refetches once and uses the version bump to decide the outcome.

vi.mock("../services/api", () => ({
  cancelStageGeneration: vi.fn(),
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
  resumeStage: vi.fn(async (id: string) => ({
    stage_id: id,
    stream_url: `/stages/${id}/resume`,
  })),
  getStage: vi.fn(),
  getStageGeneration: vi.fn(),
}))

vi.mock("../services/sseService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/sseService")>()
  return { ...actual, createSSEConnection: vi.fn() }
})

import {
  cancelStageGeneration,
  generateStage,
  getStage,
  getStageGeneration,
  regenerateStage,
  regenerateStageForGaps,
  resumeStage,
} from "../services/api"
import { StreamError, createSSEConnection } from "../services/sseService"
import { useStageStore } from "../store/stageStore"
import { useStream } from "./useStream"

const mockGetStage = vi.mocked(getStage)
const mockGetStageGeneration = vi.mocked(getStageGeneration)
const mockCancelStageGeneration = vi.mocked(cancelStageGeneration)
const mockGenerateStage = vi.mocked(generateStage)
const mockRegenerateStage = vi.mocked(regenerateStage)
const mockRegenerateGaps = vi.mocked(regenerateStageForGaps)
const mockResumeStage = vi.mocked(resumeStage)
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
    mockGetStageGeneration.mockReset()
    mockCancelStageGeneration.mockReset()
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

describe("useStream event and cancellation lifecycle", () => {
  beforeEach(() => {
    mockGetStage.mockReset()
    mockGetStageGeneration.mockReset()
    mockCancelStageGeneration.mockReset()
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

  it("is inert when no stage is selected", async () => {
    const { result } = renderHook(() => useStream(null))
    await expect(result.current.start()).resolves.toBeNull()
    await act(async () => result.current.cancel())
    expect(mockCreateSSE).not.toHaveBeenCalled()
    expect(mockGetStageGeneration).not.toHaveBeenCalled()
  })

  it("applies every live event and then replaces the buffer with server truth", async () => {
    mockGetStage.mockResolvedValue(makeStage({ current_version: 2, content: "# Canonical" }))
    mockCreateSSE.mockImplementation((opts) => {
      opts.onGenerationStarted?.({
        generation_id: "generation-1",
        deadline: "2026-07-21T01:00:00Z",
        action: "generate",
        total_parts: 3,
      })
      opts.onToken("partial")
      opts.onProgress?.({ stage: "spec", state: "streaming", elapsed_seconds: 1 })
      opts.onReset?.()
      opts.onToken("replacement")
      opts.onQualityGateFailed?.({
        stage: "spec",
        status: "blocked",
        kind: "missing_sections",
        findings: [],
      })
      opts.onGenerationTerminal?.({
        generation_id: "generation-1",
        status: "succeeded",
        partial_saved: false,
        refunded_credits: 0,
      })
      opts.onDone("s1")
      return { close: vi.fn() }
    })

    const { result } = renderHook(() => useStream("s1"))
    await act(async () => {
      await result.current.start("generate")
    })

    expect(result.current.generation?.generation_id).toBe("generation-1")
    expect(result.current.terminal?.status).toBe("succeeded")
    expect(useStageStore.getState().stages.s1.content).toBe("# Canonical")
    expect(useStageStore.getState().streamingContent.s1).toBeUndefined()
  })

  it.each(["generation_cancelled", "generation_timed_out", "generation_failed", "generation_blocked"])(
    "reconciles durable terminal event %s without presenting a retry error",
    async (code) => {
      sseErrors(code)
      mockGetStage.mockResolvedValue(makeStage({ status: "draft" }))
      const { result } = renderHook(() => useStream("s1"))
      await act(async () => {
        await result.current.start()
      })
      expect(result.current.error).toBeNull()
      expect(mockGetStage).toHaveBeenCalledWith("s1")
    },
  )

  it("surfaces a genuine provider error and restores server truth", async () => {
    sseErrors("provider_unavailable")
    mockGetStage.mockResolvedValue(makeStage({ status: "draft", content: "# Restored" }))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => {
      await result.current.start("regenerate")
    })
    expect(result.current.error?.code).toBe("provider_unavailable")
    expect(useStageStore.getState().stages.s1.content).toBe("# Restored")
  })

  it("requests cancellation for the durable active run and enters stopping state", async () => {
    const run = {
      id: "run-1",
      stage_id: "s1",
      action: "generate",
      status: "running",
      phase: "drafting",
      completed_parts: 1,
      total_parts: 3,
      started_at: new Date(Date.now() - 5000).toISOString(),
      deadline_at: "2026-07-21T01:00:00Z",
      heartbeat_at: "2026-07-21T00:00:00Z",
      cancel_requested_at: null,
      finished_at: null,
      result_version: null,
      error_code: null,
      partial_saved: false,
      refunded_credits: 0,
      credit_was_deducted: true,
    } as const
    mockGetStageGeneration.mockResolvedValue(run)
    mockCancelStageGeneration.mockResolvedValue(run)
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => result.current.cancel())
    expect(mockCancelStageGeneration).toHaveBeenCalledWith("s1", "run-1")
    expect(result.current.isStopping).toBe(true)
    expect(useStageStore.getState().streamProgress.s1.phase).toBe("stopping")
  })

  it("distinguishes an already-finished run from a cancellation transport failure", async () => {
    mockGetStageGeneration.mockResolvedValue(null)
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => result.current.cancel())
    expect(result.current.error?.message).toContain("no longer active")

    mockGetStageGeneration.mockRejectedValueOnce(new Error("offline"))
    await act(async () => result.current.cancel())
    expect(result.current.error).toEqual({
      code: "cancellation_failed",
      message: "offline",
    })
  })

  it.each([
    ["generate", mockGenerateStage],
    ["regenerate", mockRegenerateStage],
    ["regenerate-gaps", mockRegenerateGaps],
    // `resume` collects the chunks a partial generation already banked and paid
    // for, so it must reach POST /stages/{id}/resume and never fall through to
    // generateStage — that would re-run every chunk and re-charge the user.
    ["resume", mockResumeStage],
  ] as const)("dispatches the %s operation through its dedicated endpoint", async (action, endpoint) => {
    sseDone("s1")
    mockGetStage.mockResolvedValue(makeStage({ current_version: 2 }))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start(action) })
    expect(endpoint).toHaveBeenCalledWith("s1")
  })

  it("silently settles an explicitly aborted stream", async () => {
    sseErrors("stream_aborted")
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    expect(result.current.error).toBeNull()
    expect(mockGetStage).not.toHaveBeenCalled()
  })

  it("leaves durable terminal reconciliation to polling when the refetch fails", async () => {
    sseErrors("generation_failed")
    mockGetStage.mockRejectedValue(new Error("offline"))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    expect(result.current.error).toBeNull()
  })

  it("does not offer retry when interrupted work settled into a finalised stage", async () => {
    sseErrors("stream_interrupted")
    mockGetStage.mockResolvedValue(makeStage({ status: "finalised" }))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    expect(result.current.error).toBeNull()
  })

  it("surfaces an honest uncertainty when interrupted reconciliation is offline", async () => {
    sseErrors("stream_interrupted")
    mockGetStage.mockRejectedValue(new Error("offline"))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    expect(result.current.error?.message).toContain("couldn't confirm")
  })

  it("normalizes non-Error failures and restores the optimistic stage locally", async () => {
    mockCreateSSE.mockImplementation((opts) => {
      opts.onError("bad provider value" as unknown as Error)
      return { close: vi.fn() }
    })
    mockGetStage.mockRejectedValue(new Error("offline"))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    expect(result.current.error).toEqual({ code: "internal_error", message: "Streaming failed" })
    expect(useStageStore.getState().stages.s1.status).toBe("draft")
  })

  it("handles a stream for a stage missing from the local store", async () => {
    useStageStore.setState({ stages: {} })
    sseErrors("provider_unavailable")
    mockGetStage.mockRejectedValue(new Error("offline"))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    expect(result.current.error?.code).toBe("provider_unavailable")
    expect(useStageStore.getState().stages.s1).toBeUndefined()
  })

  it("cancels from the generation-started event and handles a non-Error failure", async () => {
    let options: Parameters<typeof createSSEConnection>[0] | undefined
    mockCreateSSE.mockImplementation((value) => {
      options = value
      return { close: vi.fn() }
    })
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => {
      void result.current.start()
      await Promise.resolve()
    })
    expect(options).toBeDefined()
    await act(async () => {
      options?.onGenerationStarted?.({
        generation_id: "g-event", deadline: "deadline", action: "regenerate", total_parts: 2,
      })
      await Promise.resolve()
    })
    mockCancelStageGeneration.mockRejectedValueOnce("bad cancellation")
    await act(async () => result.current.cancel())
    expect(mockGetStageGeneration).not.toHaveBeenCalled()
    expect(mockCancelStageGeneration).toHaveBeenCalledWith("s1", "g-event")
    expect(result.current.error?.message).toContain("Cancellation could not")
  })

  it("rejects cancellation when the durable run has already settled", async () => {
    mockGetStageGeneration.mockResolvedValue({ status: "succeeded" } as never)
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => result.current.cancel())
    expect(mockCancelStageGeneration).not.toHaveBeenCalled()
    expect(result.current.error?.code).toBe("cancellation_failed")
  })

  it("polls until detached advisory findings grow beyond the done baseline", async () => {
    vi.useFakeTimers()
    sseDone("s1")
    mockGetStage
      .mockResolvedValueOnce(makeStage({ current_version: 2, quality_gate: {
        stage: "spec", kind: "critic_findings", status: "advisory",
        findings: [{ kind: "Notice", detail: "existing", reference: null }],
      } }))
      .mockResolvedValueOnce(makeStage({ current_version: 2, quality_gate: {
        stage: "spec", kind: "critic_findings", status: "advisory",
        findings: [
          { kind: "Notice", detail: "existing", reference: null },
          { kind: "Critic", detail: "new", reference: null },
        ],
      } }))
    const { result } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    await act(async () => vi.advanceTimersByTimeAsync(4_000))
    expect(useStageStore.getState().stages.s1.quality_gate?.findings).toHaveLength(2)
    vi.useRealTimers()
  })

  it("bounds advisory polling across transient failures and non-advisory stages", async () => {
    vi.useFakeTimers()
    sseDone("s1")
    mockGetStage
      .mockResolvedValueOnce(makeStage({ current_version: 2 }))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(makeStage({ current_version: 2, quality_gate: { stage: "spec", kind: null, status: "clear" } }))
    const { result, unmount } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    await act(async () => vi.advanceTimersByTimeAsync(12_000))
    expect(mockGetStage).toHaveBeenCalledTimes(4)
    unmount()
    vi.useRealTimers()
  })

  it("cancels a detached advisory poll on unmount", async () => {
    vi.useFakeTimers()
    sseDone("s1")
    mockGetStage.mockResolvedValue(makeStage({ current_version: 2 }))
    const { result, unmount } = renderHook(() => useStream("s1"))
    await act(async () => { await result.current.start() })
    unmount()
    await act(async () => vi.advanceTimersByTimeAsync(4_000))
    expect(mockGetStage).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it("does not attach a late error to a newly selected stage", async () => {
    let rejectStream!: (error: Error) => void
    mockCreateSSE.mockImplementation((options) => {
      rejectStream = options.onError
      return { close: vi.fn() }
    })
    const { result, rerender } = renderHook(({ id }) => useStream(id), { initialProps: { id: "s1" } })
    await act(async () => {
      void result.current.start()
      await Promise.resolve()
    })
    expect(rejectStream).toBeDefined()
    rerender({ id: "s2" })
    mockGetStage.mockRejectedValue(new Error("offline"))
    await act(async () => rejectStream(new StreamError("provider_unavailable", "late")))
    expect(result.current.error).toBeNull()
  })
})

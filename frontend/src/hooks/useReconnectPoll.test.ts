import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { getStage, getStageGeneration } from "../services/api"
import { useStageStore } from "../store/stageStore"
import type { Stage } from "../types/stage"
import { useReconnectPoll } from "./useReconnectPoll"

vi.mock("../services/api", () => ({
  getStage: vi.fn(),
  getStageGeneration: vi.fn(),
}))

const mockGetStage = vi.mocked(getStage)
const mockGetGeneration = vi.mocked(getStageGeneration)

function runningGeneration() {
  const now = new Date()
  return {
    id: "run-1",
    stage_id: "stage-1",
    action: "generate" as const,
    status: "running" as const,
    phase: "drafting" as const,
    completed_parts: 1,
    total_parts: 3,
    started_at: now.toISOString(),
    deadline_at: new Date(now.getTime() + 300_000).toISOString(),
    heartbeat_at: now.toISOString(),
    cancel_requested_at: null,
    finished_at: null,
    result_version: null,
    error_code: null,
    partial_saved: false,
    refunded_credits: 0,
    credit_was_deducted: true,
  }
}

function makeStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "spec",
    content: null,
    status: "in_progress",
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

describe("useReconnectPoll", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockGetStage.mockReset()
    mockGetGeneration.mockReset()
    useStageStore.setState({ stages: {}, qualityGate: {} })
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  it("polls a server-running stage and writes the settled draft into the store", async () => {
    // First read: still generating. Second read: the detached pipeline persisted
    // the completed draft, so the poll stops and the store is updated.
    mockGetStage.mockResolvedValueOnce(
      makeStage({ status: "draft", content: "# Spec", current_version: 1 }),
    )
    mockGetGeneration
      .mockResolvedValueOnce(runningGeneration())
      .mockResolvedValueOnce({ ...runningGeneration(), status: "succeeded" })

    renderHook(() => useReconnectPoll("stage-1", false))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(mockGetGeneration).toHaveBeenCalledTimes(1)
    expect(mockGetStage).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    const settled = useStageStore.getState().stages["stage-1"]
    expect(settled?.status).toBe("draft")
    expect(settled?.content).toBe("# Spec")
    expect(mockGetStage).toHaveBeenCalledTimes(1)

    // No further polling once the stage has settled.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    expect(mockGetStage).toHaveBeenCalledTimes(1)
  })

  it("does not poll when this client owns the live stream", async () => {
    renderHook(() => useReconnectPoll("stage-1", true))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    expect(mockGetStage).not.toHaveBeenCalled()
  })

  it("does not poll when there is no in-progress stage", async () => {
    renderHook(() => useReconnectPoll(null, false))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    expect(mockGetStage).not.toHaveBeenCalled()
  })

  it("stops polling after unmount", async () => {
    mockGetStage.mockResolvedValue(makeStage({ status: "in_progress" }))
    mockGetGeneration.mockResolvedValue(runningGeneration())

    const { unmount } = renderHook(() => useReconnectPoll("stage-1", false))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(mockGetGeneration).toHaveBeenCalledTimes(1)
    expect(mockGetStage).not.toHaveBeenCalled()

    unmount()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })
    expect(mockGetGeneration).toHaveBeenCalledTimes(1)
    expect(mockGetStage).not.toHaveBeenCalled()
  })
})

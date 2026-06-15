import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { GenerationEstimate } from "../services/api"

// Mock the API module so the store never touches the network.
const fetchGenerationEstimates = vi.fn(
  async (): Promise<GenerationEstimate[]> => [],
)
vi.mock("../services/api", () => ({
  fetchGenerationEstimates: () => fetchGenerationEstimates(),
}))

import { useGenerationEstimatesStore } from "./generationEstimatesStore"

const SAMPLE: GenerationEstimate[] = [
  { provider: "anthropic", stage: "spec", operation: "generate", p50: 22, p90: 58, n: 300 },
]

describe("useGenerationEstimatesStore", () => {
  beforeEach(() => {
    fetchGenerationEstimates.mockReset()
    useGenerationEstimatesStore.setState({
      estimates: [],
      status: "idle",
      fetchedAt: null,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("fetches once and populates the estimates on first ensureLoaded", async () => {
    fetchGenerationEstimates.mockResolvedValue(SAMPLE)

    await useGenerationEstimatesStore.getState().ensureLoaded()

    const state = useGenerationEstimatesStore.getState()
    expect(fetchGenerationEstimates).toHaveBeenCalledTimes(1)
    expect(state.status).toBe("loaded")
    expect(state.estimates).toEqual(SAMPLE)
    expect(state.fetchedAt).not.toBeNull()
  })

  it("dedupes: a second ensureLoaded while fresh does not refetch", async () => {
    fetchGenerationEstimates.mockResolvedValue(SAMPLE)

    await useGenerationEstimatesStore.getState().ensureLoaded()
    await useGenerationEstimatesStore.getState().ensureLoaded()

    expect(fetchGenerationEstimates).toHaveBeenCalledTimes(1)
  })

  it("settles to 'loaded' with an empty list when no live data is available", async () => {
    // fetchGenerationEstimates swallows its own errors and returns [] — the
    // store must still mark itself loaded so consumers stop waiting and fall
    // back to the heuristic deterministically.
    fetchGenerationEstimates.mockResolvedValue([])

    await useGenerationEstimatesStore.getState().ensureLoaded()

    const state = useGenerationEstimatesStore.getState()
    expect(state.status).toBe("loaded")
    expect(state.estimates).toEqual([])
  })

  it("does not start a second fetch while one is in flight", async () => {
    let resolve: (value: GenerationEstimate[]) => void = () => {}
    fetchGenerationEstimates.mockReturnValue(
      new Promise((r) => {
        resolve = r
      }),
    )

    const first = useGenerationEstimatesStore.getState().ensureLoaded()
    // status is now "loading"; a concurrent call must be a no-op.
    const second = useGenerationEstimatesStore.getState().ensureLoaded()
    resolve(SAMPLE)
    await Promise.all([first, second])

    expect(fetchGenerationEstimates).toHaveBeenCalledTimes(1)
  })
})

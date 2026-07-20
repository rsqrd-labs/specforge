import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { getCredits } from "../services/api"
import { useCredits } from "./useCredits"

vi.mock("../services/api", () => ({ getCredits: vi.fn() }))

const credits = (balance: number) => ({
  balance,
  generation_cost: 10,
  billing_debt_credits: 0,
})

describe("useCredits", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(getCredits).mockReset()
  })
  afterEach(() => vi.useRealTimers())

  it("loads and refreshes the balance every 30 seconds", async () => {
    vi.mocked(getCredits)
      .mockResolvedValueOnce(credits(7))
      .mockResolvedValueOnce(credits(9))
    const { result } = renderHook(() => useCredits())
    await act(async () => { await Promise.resolve() })
    expect(result.current).toEqual({ balance: 7, isLoading: false })
    await act(async () => vi.advanceTimersByTimeAsync(30_000))
    expect(result.current.balance).toBe(9)
  })

  it("reports an unavailable balance and ignores completion after unmount", async () => {
    vi.mocked(getCredits).mockRejectedValueOnce(new Error("offline"))
    const first = renderHook(() => useCredits())
    await act(async () => { await Promise.resolve() })
    expect(first.result.current.isLoading).toBe(false)
    expect(first.result.current.balance).toBeNull()

    let resolve!: (value: ReturnType<typeof credits>) => void
    vi.mocked(getCredits).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const second = renderHook(() => useCredits())
    second.unmount()
    await act(async () => resolve(credits(100)))
    expect(second.result.current.balance).toBeNull()
  })
})

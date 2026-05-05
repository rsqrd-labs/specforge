import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createSSEConnection } from "../services/sseService"

const apiMocks = vi.hoisted(() => ({
  accessToken: null as string | null,
  csrfToken: null as string | null,
  refreshAccessToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock("../services/api", () => ({
  getAccessToken: () => apiMocks.accessToken,
  getCsrfToken: () => Promise.resolve(apiMocks.csrfToken),
  refreshAccessToken: apiMocks.refreshAccessToken,
}))

function makeStream(text: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })
}

function mockFetchOk(body: string) {
  return Promise.resolve(
    new Response(makeStream(body), {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
  )
}

function mockFetchFail(status = 503) {
  return Promise.resolve(new Response(null, { status }))
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(console, "warn").mockImplementation(() => {})
  apiMocks.accessToken = null
  apiMocks.csrfToken = null
  apiMocks.refreshAccessToken.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe("createSSEConnection retry behaviour", () => {
  it("does not call onError when fetch fails twice then succeeds", async () => {
    const doneBody =
      'data: {"token":"hi"}\n\ndata: {"done":true,"stage_id":"s1"}\n\n'

    let callCount = 0
    vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      callCount++
      return callCount <= 2 ? mockFetchFail() : mockFetchOk(doneBody)
    })

    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    const onEval = vi.fn()

    createSSEConnection("/stream", onToken, onDone, onError, onEval)

    // Attempt 1 fails → backoff 1 000 ms scheduled
    await vi.advanceTimersByTimeAsync(1000)
    // Attempt 2 fails → backoff 2 000 ms scheduled
    await vi.advanceTimersByTimeAsync(2000)
    // Attempt 3 succeeds — flush remaining async work
    await vi.runAllTimersAsync()

    expect(onError).not.toHaveBeenCalled()
    expect(onDone).toHaveBeenCalledWith("s1")
    expect(console.warn).toHaveBeenCalledTimes(2)
  })

  it("calls onError exactly once after three consecutive transport failures", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => mockFetchFail(503))

    const onError = vi.fn()

    createSSEConnection("/stream", vi.fn(), vi.fn(), onError, vi.fn())

    // Three failed attempts with backoffs: 1 s → 2 s → 4 s
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)
    await vi.runAllTimersAsync()

    expect(onError).toHaveBeenCalledTimes(1)
    expect(console.warn).toHaveBeenCalledTimes(3)
  })

  it("does not retry on application-level SSE error events", async () => {
    const errorBody =
      'data: {"error":"rate_limit_exceeded","retry_after":60}\n\n'
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      mockFetchOk(errorBody),
    )

    const onError = vi.fn()

    createSSEConnection("/stream", vi.fn(), vi.fn(), onError, vi.fn())

    await vi.runAllTimersAsync()

    expect(onError).toHaveBeenCalledTimes(1)
    expect(console.warn).not.toHaveBeenCalled()
  })

  it("refreshes the access token once when the stream request gets a 401", async () => {
    const doneBody = 'data: {"done":true,"stage_id":"s1"}\n\n'
    apiMocks.accessToken = "expired"
    apiMocks.csrfToken = "csrf-1"
    apiMocks.refreshAccessToken.mockImplementation(async () => {
      apiMocks.accessToken = "fresh"
      apiMocks.csrfToken = "csrf-2"
      return "fresh"
    })

    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => mockFetchFail(401))
      .mockImplementationOnce(() => mockFetchOk(doneBody))

    const onDone = vi.fn()
    const onError = vi.fn()

    createSSEConnection("/stream", vi.fn(), onDone, onError, vi.fn())

    await vi.runAllTimersAsync()

    const secondHeaders = (
      vi.mocked(globalThis.fetch).mock.calls[1][1] as RequestInit
    ).headers as Headers
    expect(apiMocks.refreshAccessToken).toHaveBeenCalledTimes(1)
    expect(secondHeaders.get("Authorization")).toBe("Bearer fresh")
    expect(secondHeaders.get("X-CSRF-Token")).toBe("csrf-2")
    expect(onDone).toHaveBeenCalledWith("s1")
    expect(onError).not.toHaveBeenCalled()
    expect(console.warn).not.toHaveBeenCalled()
  })

  it("stops retrying when close() is called during a backoff delay", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => mockFetchFail(503))

    const onError = vi.fn()

    const { close } = createSSEConnection(
      "/stream",
      vi.fn(),
      vi.fn(),
      onError,
      vi.fn(),
    )

    // Let the first attempt fail (backoff 1 000 ms queued)
    await vi.advanceTimersByTimeAsync(0)
    // Cancel before the backoff fires
    close()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.runAllTimersAsync()

    expect(onError).not.toHaveBeenCalled()
    // warn was logged once before close() interrupted
    expect(console.warn).toHaveBeenCalledTimes(1)
  })
})

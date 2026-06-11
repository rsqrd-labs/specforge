import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createSSEConnection } from "../services/sseService"

const apiMocks = vi.hoisted(() => ({
  accessToken: null as string | null,
  csrfToken: null as string | null,
  getCsrfToken: vi.fn<() => Promise<string | null>>(),
  refreshAccessToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock("../services/api", () => ({
  getAccessToken: () => apiMocks.accessToken,
  getCsrfToken: apiMocks.getCsrfToken,
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
  apiMocks.getCsrfToken.mockReset()
  apiMocks.getCsrfToken.mockImplementation(() =>
    Promise.resolve(apiMocks.csrfToken),
  )
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

  it("maps finalised stage errors to product-facing copy", async () => {
    const errorBody =
      'data: {"error":"stage_not_generatable","detail":"Stage status ' +
      "'finalised' is not generatable\"}\n\n"
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      mockFetchOk(errorBody),
    )

    const onError = vi.fn()

    createSSEConnection("/stream", vi.fn(), vi.fn(), onError, vi.fn())

    await vi.runAllTimersAsync()

    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0].message).toBe(
      "This stage is already complete. Use rollback or edit the draft before " +
        "generating again.",
    )
  })

  it("maps provider timeouts separately from provider failures", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      mockFetchOk('data: {"error":"provider_timeout","timeout_seconds":300}\n\n'),
    )

    const onError = vi.fn()

    createSSEConnection("/stream", vi.fn(), vi.fn(), onError, vi.fn())

    await vi.runAllTimersAsync()

    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0].message).toBe(
      "Generation timed out. The model did not finish this stage in time. " +
        "Your workspace is safe. Try again; long stages may need another run.",
    )
  })

  it("treats a stream ending before done as a retryable failure", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      mockFetchOk('data: {"token":"partial"}\n\n'),
    )

    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()

    createSSEConnection("/stream", onToken, onDone, onError, vi.fn())

    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)
    await vi.runAllTimersAsync()

    expect(onToken).toHaveBeenCalled()
    expect(onDone).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0].message).toMatch(/before generation completed/i)
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

  it("uses a fresh CSRF token for each retry attempt", async () => {
    const doneBody = 'data: {"done":true,"stage_id":"s1"}\n\n'
    apiMocks.accessToken = "valid"
    apiMocks.getCsrfToken
      .mockResolvedValueOnce("csrf-used")
      .mockResolvedValueOnce("csrf-fresh")

    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => mockFetchFail(403))
      .mockImplementationOnce(() => mockFetchOk(doneBody))

    const onDone = vi.fn()
    const onError = vi.fn()

    createSSEConnection("/stream", vi.fn(), onDone, onError, vi.fn())

    await vi.advanceTimersByTimeAsync(1000)
    await vi.runAllTimersAsync()

    const firstHeaders = (
      vi.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit
    ).headers as Headers
    const secondHeaders = (
      vi.mocked(globalThis.fetch).mock.calls[1][1] as RequestInit
    ).headers as Headers

    expect(apiMocks.getCsrfToken).toHaveBeenCalledTimes(2)
    expect(firstHeaders.get("X-CSRF-Token")).toBe("csrf-used")
    expect(secondHeaders.get("X-CSRF-Token")).toBe("csrf-fresh")
    expect(onDone).toHaveBeenCalledWith("s1")
    expect(onError).not.toHaveBeenCalled()
  })

  it("surfaces a quality_gate_failed event and stops without retrying", async () => {
    const gateBody =
      'data: {"quality_gate_failed":{"stage":"plan","kind":"critic_findings",' +
      '"findings":[{"kind":"MissingSection","detail":"No ADR","reference":"ADR"}]}}\n\n'
    vi.spyOn(globalThis, "fetch").mockImplementation(() => mockFetchOk(gateBody))

    const onDone = vi.fn()
    const onError = vi.fn()
    const onGate = vi.fn()

    createSSEConnection("/stream", vi.fn(), onDone, onError, vi.fn(), onGate)

    await vi.runAllTimersAsync()

    expect(onGate).toHaveBeenCalledTimes(1)
    expect(onGate.mock.calls[0][0]).toMatchObject({
      stage: "plan",
      findings: [{ kind: "MissingSection", detail: "No ADR", reference: "ADR" }],
    })
    // Terminal: surfaced as an error, the done callback never fires, no retry.
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0].code).toBe("quality_gate_failed")
    expect(onDone).not.toHaveBeenCalled()
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

describe("createSSEConnection progress heartbeats", () => {
  it("routes progress events to onProgress and never to onToken", async () => {
    const body =
      'data: {"progress":{"stage":"spec","state":"generating","elapsed_seconds":20}}\n\n' +
      'data: {"token":"## Overview"}\n\n' +
      'data: {"done":true,"stage_id":"s1"}\n\n'

    vi.spyOn(globalThis, "fetch").mockImplementation(() => mockFetchOk(body))

    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    const onEval = vi.fn()
    const onQualityGate = vi.fn()
    const onProgress = vi.fn()

    createSSEConnection(
      "/stream",
      onToken,
      onDone,
      onError,
      onEval,
      onQualityGate,
      onProgress,
    )

    await vi.runAllTimersAsync()

    expect(onProgress).toHaveBeenCalledWith({
      stage: "spec",
      state: "generating",
      elapsed_seconds: 20,
    })
    expect(onToken).toHaveBeenCalledTimes(1)
    expect(onToken).toHaveBeenCalledWith("## Overview")
    expect(onDone).toHaveBeenCalledWith("s1")
    expect(onError).not.toHaveBeenCalled()
  })

  it("routes stream_reset to onReset so the live draft buffer is cleared", async () => {
    const body =
      'data: {"token":"draft text that will be replaced"}\n\n' +
      'data: {"stream_reset":true}\n\n' +
      'data: {"token":"## Canonical artifact"}\n\n' +
      'data: {"done":true,"stage_id":"s3"}\n\n'

    vi.spyOn(globalThis, "fetch").mockImplementation(() => mockFetchOk(body))

    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    const onReset = vi.fn()

    createSSEConnection(
      "/stream",
      onToken,
      onDone,
      onError,
      vi.fn(),
      vi.fn(),
      vi.fn(),
      onReset,
    )

    await vi.runAllTimersAsync()

    expect(onReset).toHaveBeenCalledTimes(1)
    // Reset is a control event: never appended as content.
    expect(onToken).toHaveBeenCalledTimes(2)
    expect(onToken).toHaveBeenNthCalledWith(1, "draft text that will be replaced")
    expect(onToken).toHaveBeenNthCalledWith(2, "## Canonical artifact")
    expect(onDone).toHaveBeenCalledWith("s3")
    expect(onError).not.toHaveBeenCalled()
  })

  it("ignores progress events when no onProgress handler is provided", async () => {
    const body =
      'data: {"progress":{"stage":"plan","state":"generating","elapsed_seconds":5}}\n\n' +
      'data: {"done":true,"stage_id":"s2"}\n\n'

    vi.spyOn(globalThis, "fetch").mockImplementation(() => mockFetchOk(body))

    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()

    createSSEConnection("/stream", onToken, onDone, onError)

    await vi.runAllTimersAsync()

    expect(onToken).not.toHaveBeenCalled()
    expect(onDone).toHaveBeenCalledWith("s2")
    expect(onError).not.toHaveBeenCalled()
  })
})

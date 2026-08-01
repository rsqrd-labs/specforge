import { beforeEach, describe, expect, it, vi } from "vitest"

// Same low-level axios-mocking harness as api.refresh.test.ts: the behaviour
// under test lives inside the real module logic, so it runs against the real
// `./api` with only axios itself faked.
const axiosMock = vi.hoisted(() => {
  const instance = () => ({
    defaults: {},
    get: vi.fn(),
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  })
  const apiInstance = instance()
  const refreshInstance = instance()
  return {
    apiInstance,
    refreshInstance,
    create: vi
      .fn()
      .mockReturnValueOnce(apiInstance)
      .mockReturnValueOnce(refreshInstance),
  }
})

vi.mock("axios", () => {
  class AxiosHeaders {
    private readonly values = new Map<string, string>()
    static from(headers: unknown): AxiosHeaders {
      if (headers instanceof AxiosHeaders) return headers
      return new AxiosHeaders()
    }
    set(key: string, value: string): void {
      this.values.set(key.toLowerCase(), value)
    }
    get(key: string): string | null {
      return this.values.get(key.toLowerCase()) ?? null
    }
  }

  return {
    default: {
      create: axiosMock.create,
      isAxiosError: (error: unknown) =>
        Boolean(error && typeof error === "object" && "isAxiosError" in error),
    },
    AxiosHeaders,
  }
})

/** An axios rejection that never produced a response — a blocked proxy, a
 *  rejected CORS preflight, a timeout, an offline browser. */
function transportRejection(code = "ERR_NETWORK") {
  return { isAxiosError: true, code, response: undefined, config: {} }
}

/** An axios rejection the server actually answered. */
function httpRejection(status: number) {
  return { isAxiosError: true, response: { status }, config: {} }
}

beforeEach(async () => {
  axiosMock.apiInstance.get.mockReset()
  axiosMock.refreshInstance.post.mockReset()
  const { setAccessToken } = await import("./api")
  setAccessToken("reset-guard")
  setAccessToken(null)
})

describe("isTransportError", () => {
  it("identifies a request that never produced a response", async () => {
    const { isTransportError } = await import("./api")
    expect(isTransportError(transportRejection())).toBe(true)
  })

  it("does not claim a transport failure when the server answered", async () => {
    const { isTransportError } = await import("./api")
    expect(isTransportError(httpRejection(401))).toBe(false)
    expect(isTransportError(httpRejection(500))).toBe(false)
  })

  it("treats a deliberate cancellation as a client decision, not an outage", async () => {
    const { isTransportError } = await import("./api")
    expect(isTransportError(transportRejection("ERR_CANCELED"))).toBe(false)
  })

  it("recognises a TransportError thrown by a non-axios wrapper", async () => {
    const { isTransportError, TransportError } = await import("./api")
    expect(isTransportError(new TransportError())).toBe(true)
    expect(isTransportError(new Error("Not authenticated"))).toBe(false)
  })
})

describe("access-token retention across failures", () => {
  /**
   * The rejection handler api.ts registers on its own response interceptor —
   * i.e. the exact production wiring, including the private `refreshApi`
   * instance that callers cannot pass in themselves.
   */
  async function interceptorReject(error: unknown): Promise<unknown> {
    await import("./api")
    const handler = axiosMock.apiInstance.interceptors.response.use.mock.calls[0][1] as (
      e: unknown,
    ) => Promise<unknown>
    return handler(error).catch((cause: unknown) => cause)
  }

  // The regression: a blocked request discarded a perfectly good token, so the
  // retry found none, tried to refresh, was blocked too, and the user was
  // bounced to the landing page as if signed out.
  it("keeps the token when a request never reached the API", async () => {
    const { setAccessToken, getAccessToken } = await import("./api")
    setAccessToken("live-token")

    await interceptorReject(transportRejection())

    expect(getAccessToken()).toBe("live-token")
  })

  it("still discards the token when the API answered with an unretryable 401", async () => {
    const { setAccessToken, getAccessToken } = await import("./api")
    setAccessToken("stale-token")

    await interceptorReject({ ...httpRejection(401), config: { _retry: true } })

    expect(getAccessToken()).toBeNull()
  })

  it("keeps the token when the refresh itself is blocked", async () => {
    const { setAccessToken, getAccessToken } = await import("./api")
    setAccessToken("live-token")
    axiosMock.refreshInstance.post.mockRejectedValue(transportRejection())

    await interceptorReject(httpRejection(401))

    expect(getAccessToken()).toBe("live-token")
  })

  it("discards the token when the refresh is definitively rejected", async () => {
    const { setAccessToken, getAccessToken } = await import("./api")
    setAccessToken("stale-token")
    axiosMock.refreshInstance.post.mockRejectedValue(httpRejection(401))

    await interceptorReject(httpRejection(401))

    expect(getAccessToken()).toBeNull()
  })
})

describe("getCurrentUser failure reporting", () => {
  it("reports a blocked refresh as a transport failure, not as a dead session", async () => {
    const { getCurrentUser, isTransportError } = await import("./api")
    axiosMock.refreshInstance.post.mockRejectedValue(transportRejection())

    const error = await getCurrentUser().catch((cause: unknown) => cause)

    expect(isTransportError(error)).toBe(true)
  })

  it("reports a definitively rejected refresh as a dead session", async () => {
    const { getCurrentUser, isTransportError } = await import("./api")
    axiosMock.refreshInstance.post.mockRejectedValue(httpRejection(401))

    const error = await getCurrentUser().catch((cause: unknown) => cause)

    expect(isTransportError(error)).toBe(false)
    expect((error as Error).message).toBe("Not authenticated")
  })
})

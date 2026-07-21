import { describe, expect, it, vi } from "vitest"

const axiosMock = vi.hoisted(() => {
  const apiInstance = {
    defaults: {},
    get: vi.fn(),
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }
  const refreshInstance = {
    defaults: {},
    get: vi.fn(),
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }
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
      if (headers instanceof AxiosHeaders) {
        return headers
      }
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

describe("CSRF token handling", () => {
  it("does not request a CSRF token without an authenticated access token", async () => {
    const { getCsrfToken, setAccessToken } = await import("./api")
    setAccessToken(null)
    axiosMock.refreshInstance.get.mockClear()
    await expect(getCsrfToken()).resolves.toBeNull()
    expect(axiosMock.refreshInstance.get).not.toHaveBeenCalled()
  })

  it("fetches a new one-time CSRF token for each call", async () => {
    const { getCsrfToken, setAccessToken } = await import("./api")

    axiosMock.refreshInstance.get
      .mockResolvedValueOnce({ data: { csrf_token: "csrf-1" } })
      .mockResolvedValueOnce({ data: { csrf_token: "csrf-2" } })

    setAccessToken("access-token")

    await expect(getCsrfToken()).resolves.toBe("csrf-1")
    await expect(getCsrfToken()).resolves.toBe("csrf-2")

    expect(axiosMock.refreshInstance.get).toHaveBeenCalledTimes(2)
    const firstConfig = axiosMock.refreshInstance.get.mock.calls[0][1] as {
      headers: { get: (key: string) => string | null }
    }
    expect(axiosMock.refreshInstance.get.mock.calls[0][0]).toBe(
      "/auth/csrf-token",
    )
    expect(firstConfig.headers.get("Authorization")).toBe("Bearer access-token")
  })

  it("refreshes and retries once when the prefetch 401s on an expired token", async () => {
    // Regression for the idle-then-Generate bug: an expired access token makes the
    // csrf-token prefetch 401. That 401 must be refreshed+retried *inside*
    // getCsrfToken (which rides `refreshApi`, no response interceptor) so it never
    // leaks into `api`'s response interceptor — where it would be mis-attributed
    // to the mutating request and resolve it with the csrf-token response.
    const { getCsrfToken, setAccessToken } = await import("./api")

    axiosMock.refreshInstance.get.mockClear()
    axiosMock.refreshInstance.post.mockClear()

    setAccessToken("expired-token")

    axiosMock.refreshInstance.get
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 401 } })
      .mockResolvedValueOnce({ data: { csrf_token: "csrf-after-refresh" } })
    axiosMock.refreshInstance.post.mockResolvedValueOnce({
      data: { access_token: "fresh-token" },
    })

    await expect(getCsrfToken()).resolves.toBe("csrf-after-refresh")

    expect(axiosMock.refreshInstance.post).toHaveBeenCalledWith("/auth/refresh")
    expect(axiosMock.refreshInstance.get).toHaveBeenCalledTimes(2)
    // The retry carries the freshly minted access token, not the expired one.
    const retryConfig = axiosMock.refreshInstance.get.mock.calls[1][1] as {
      headers: { get: (key: string) => string | null }
    }
    expect(retryConfig.headers.get("Authorization")).toBe("Bearer fresh-token")
  })

  it("returns null (no leak) when the refresh itself fails after a 401", async () => {
    const { getCsrfToken, setAccessToken } = await import("./api")

    axiosMock.refreshInstance.get.mockClear()
    axiosMock.refreshInstance.post.mockClear()

    setAccessToken("expired-token")

    axiosMock.refreshInstance.get.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 401 },
    })
    axiosMock.refreshInstance.post.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 401 },
    })

    await expect(getCsrfToken()).resolves.toBeNull()
    expect(axiosMock.refreshInstance.get).toHaveBeenCalledTimes(1)
  })
})

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
})

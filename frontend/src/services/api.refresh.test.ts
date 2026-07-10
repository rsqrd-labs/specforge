import { beforeEach, describe, expect, it, vi } from "vitest"

// Same low-level axios-mocking harness as api.csrf.test.ts: refreshAccessToken's
// circuit breaker lives inside the real module logic, so it must be exercised
// against the real `./api`, not a mocked one — only axios itself is faked.
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

beforeEach(async () => {
  axiosMock.refreshInstance.post.mockReset()
  // Reset module-level state (accessToken + the session-expired latch) via the
  // public API rather than vi.resetModules() — resetting modules would replay
  // api.ts's top-level axios.create() calls past the once-queue this harness
  // primes exactly twice. setAccessToken with a truthy value clears the latch;
  // the subsequent null clears the token itself.
  const { setAccessToken } = await import("./api")
  setAccessToken("reset-guard")
  setAccessToken(null)
})

describe("refreshAccessToken session-death circuit breaker", () => {
  it("latches after a definitive 401 and skips the network on the next call", async () => {
    const { refreshAccessToken, isSessionExpired } = await import("./api")

    axiosMock.refreshInstance.post.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 401 },
    })

    await expect(refreshAccessToken()).resolves.toBeNull()
    expect(isSessionExpired()).toBe(true)
    expect(axiosMock.refreshInstance.post).toHaveBeenCalledTimes(1)

    // A second caller (e.g. the next 30s poll) must not hit the network again —
    // the server can only answer the same way until the user signs in again.
    await expect(refreshAccessToken()).resolves.toBeNull()
    expect(axiosMock.refreshInstance.post).toHaveBeenCalledTimes(1)
  })

  it("does not latch on a transient failure — the next attempt still tries the network", async () => {
    const { refreshAccessToken, isSessionExpired } = await import("./api")

    axiosMock.refreshInstance.post.mockRejectedValueOnce(new Error("network error"))
    await expect(refreshAccessToken()).resolves.toBeNull()
    expect(isSessionExpired()).toBe(false)

    axiosMock.refreshInstance.post.mockResolvedValueOnce({
      data: { access_token: "fresh-token" },
    })
    await expect(refreshAccessToken()).resolves.toBe("fresh-token")
    expect(axiosMock.refreshInstance.post).toHaveBeenCalledTimes(2)
  })

  it("clears the latch once a fresh token proves the session is alive again", async () => {
    const { refreshAccessToken, setAccessToken, isSessionExpired } = await import(
      "./api"
    )

    axiosMock.refreshInstance.post.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 401 },
    })
    await refreshAccessToken()
    expect(isSessionExpired()).toBe(true)

    // A real login (AuthCallback) or a successful refresh calls setAccessToken
    // with a real token — that is proof the session is alive, so it must
    // re-arm future refresh attempts.
    setAccessToken("logged-in-again")
    expect(isSessionExpired()).toBe(false)

    axiosMock.refreshInstance.post.mockResolvedValueOnce({
      data: { access_token: "next-token" },
    })
    await expect(refreshAccessToken()).resolves.toBe("next-token")
    expect(axiosMock.refreshInstance.post).toHaveBeenCalledTimes(2)
  })

  it("notifies onSessionExpired listeners exactly once across repeated failed callers", async () => {
    const { refreshAccessToken, onSessionExpired } = await import("./api")

    const listener = vi.fn()
    const unsubscribe = onSessionExpired(listener)

    axiosMock.refreshInstance.post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 401 },
    })

    // Simulates three independent pollers (credits, GitHub sync, billing
    // status) each discovering the dead session in turn.
    await refreshAccessToken()
    await refreshAccessToken()
    await refreshAccessToken()

    // One alarm, not one per poller — repeated "your session expired"
    // notifications would be exactly the false-alarm noise to avoid.
    expect(listener).toHaveBeenCalledTimes(1)
    expect(axiosMock.refreshInstance.post).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  it("re-probes after the cooldown window lapses instead of staying latched forever", async () => {
    // The refresh-token cookie is shared across tabs: another tab (or a fresh
    // sign-in) can make the session valid again without this tab knowing. A
    // permanent latch would leave a stale tab stuck until a hard reload even
    // after the underlying session recovered — the cooldown must expire.
    vi.useFakeTimers()
    try {
      const { refreshAccessToken, isSessionExpired } = await import("./api")

      axiosMock.refreshInstance.post.mockRejectedValueOnce({
        isAxiosError: true,
        response: { status: 401 },
      })
      await refreshAccessToken()
      expect(isSessionExpired()).toBe(true)

      await vi.advanceTimersByTimeAsync(59_000)
      expect(isSessionExpired()).toBe(true) // still inside the window

      await vi.advanceTimersByTimeAsync(2_000) // now past 60s total
      expect(isSessionExpired()).toBe(false)

      axiosMock.refreshInstance.post.mockResolvedValueOnce({
        data: { access_token: "recovered-token" },
      })
      await expect(refreshAccessToken()).resolves.toBe("recovered-token")
      expect(axiosMock.refreshInstance.post).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it("does not let a stale in-flight refresh's 401 clobber a newer, already-proven session", async () => {
    // Guards the theoretical race: a refresh call is in flight when some other
    // path (e.g. a fresh login) calls setAccessToken with a real token. If the
    // in-flight call later rejects with a 401, that rejection describes a
    // session that no longer matters and must not re-latch the app into
    // "signed out" right after the user just proved they're signed in.
    const { refreshAccessToken, setAccessToken, isSessionExpired } = await import(
      "./api"
    )

    let rejectPendingRefresh!: (reason: unknown) => void
    axiosMock.refreshInstance.post.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectPendingRefresh = reject
        }),
    )

    const pendingRefresh = refreshAccessToken()

    // A fresh login completes via a different path (AuthCallback), not
    // through refreshAccessToken, while the stale call above is still pending.
    setAccessToken("freshly-logged-in-token")
    expect(isSessionExpired()).toBe(false)

    // Now the stale call finally rejects with a definitive 401.
    rejectPendingRefresh({ isAxiosError: true, response: { status: 401 } })
    await expect(pendingRefresh).resolves.toBeNull()

    expect(isSessionExpired()).toBe(false)
  })

  it("does not let a stale in-flight refresh's 401 clobber a voluntary logout, even mid-logout", async () => {
    // Guards the companion race to the one above: a refresh call (e.g. a
    // background poller reacting to an earlier 401) is already in flight when
    // the user clicks "Sign out". logout() revokes the session server-side,
    // so the stale refresh's eventual 401 describes a death we already caused
    // deliberately — it must not fire the "your session expired" alarm. The
    // rejection is forced to land *before* logout()'s own POST has resolved,
    // to prove the generation bump happens synchronously at the top of
    // logout() rather than after its await (a bug the naive fix had).
    const { refreshAccessToken, logout, onSessionExpired, isSessionExpired } =
      await import("./api")

    const listener = vi.fn()
    const unsubscribe = onSessionExpired(listener)

    let rejectPendingRefresh!: (reason: unknown) => void
    axiosMock.refreshInstance.post.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectPendingRefresh = reject
        }),
    )
    const pendingRefresh = refreshAccessToken()

    let resolveLogoutPost!: (value: unknown) => void
    axiosMock.refreshInstance.post.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveLogoutPost = resolve
        }),
    )
    const logoutPromise = logout()

    // The stale refresh rejects while logout()'s own POST is still pending.
    rejectPendingRefresh({ isAxiosError: true, response: { status: 401 } })
    await expect(pendingRefresh).resolves.toBeNull()

    expect(isSessionExpired()).toBe(false)
    expect(listener).not.toHaveBeenCalled()

    resolveLogoutPost({ data: {} })
    await logoutPromise

    expect(isSessionExpired()).toBe(false)
    expect(listener).not.toHaveBeenCalled()
    unsubscribe()
  })
})

import { beforeEach, describe, expect, it, vi } from "vitest"
import type { User } from "../types/user"

const getCurrentUser = vi.hoisted(() => vi.fn())
const isTransportError = vi.hoisted(() => vi.fn(() => false))
vi.mock("../services/api", () => ({ getCurrentUser, isTransportError }))

import { useUserStore } from "./userStore"

const user: User = {
  id: "user-1",
  email: "owner@example.com",
  google_id: "google-user-1",
  name: "Owner",
  avatar_url: null,
  created_at: "2026-01-01T00:00:00Z",
  credit_balance: 100,
}

describe("useUserStore", () => {
  beforeEach(() => {
    getCurrentUser.mockReset()
    isTransportError.mockReset()
    isTransportError.mockReturnValue(false)
    useUserStore.setState({ user: null, isLoading: false, reachability: "ok" })
  })

  it("sets and clears a session explicitly", () => {
    useUserStore.getState().setUser(user)
    expect(useUserStore.getState().user).toEqual(user)
    useUserStore.getState().clearUser()
    expect(useUserStore.getState().user).toBeNull()
  })

  it("loads the current user and settles loading", async () => {
    getCurrentUser.mockResolvedValue(user)
    await useUserStore.getState().fetchMe()
    expect(useUserStore.getState()).toEqual({
      ...useUserStore.getState(),
      user,
      isLoading: false,
    })
  })

  it("clears stale identity when session validation fails", async () => {
    useUserStore.setState({ user })
    getCurrentUser.mockRejectedValue(new Error("unauthorized"))
    await useUserStore.getState().fetchMe()
    expect(useUserStore.getState()).toMatchObject({
      user: null,
      isLoading: false,
      reachability: "ok",
    })
  })

  // The corporate-proxy regression: a request that never reached the API used
  // to be indistinguishable from a rejected session, so it wiped `user` and let
  // ProtectedRoute bounce a signed-in person to the landing page.
  it("keeps the session and flags unreachable when the API cannot be reached", async () => {
    useUserStore.setState({ user })
    getCurrentUser.mockRejectedValue(new Error("blocked by proxy"))
    isTransportError.mockReturnValue(true)

    await useUserStore.getState().fetchMe()

    expect(useUserStore.getState()).toMatchObject({
      user,
      isLoading: false,
      reachability: "unreachable",
    })
  })

  it("does not invent a session for a logged-out visitor when the API is unreachable", async () => {
    getCurrentUser.mockRejectedValue(new Error("blocked by proxy"))
    isTransportError.mockReturnValue(true)

    await useUserStore.getState().fetchMe()

    expect(useUserStore.getState()).toMatchObject({
      user: null,
      reachability: "unreachable",
    })
  })

  it("does not carry a stale unreachable flag across an explicit sign-out", async () => {
    useUserStore.setState({ user, reachability: "unreachable" })
    useUserStore.getState().clearUser()
    expect(useUserStore.getState()).toMatchObject({ user: null, reachability: "ok" })
  })

  it("clears the unreachable flag once the API answers again", async () => {
    useUserStore.setState({ reachability: "unreachable" })
    getCurrentUser.mockResolvedValue(user)

    await useUserStore.getState().fetchMe()

    expect(useUserStore.getState()).toMatchObject({ user, reachability: "ok" })
  })
})

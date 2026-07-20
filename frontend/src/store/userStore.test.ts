import { beforeEach, describe, expect, it, vi } from "vitest"
import type { User } from "../types/user"

const getCurrentUser = vi.hoisted(() => vi.fn())
vi.mock("../services/api", () => ({ getCurrentUser }))

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
    useUserStore.setState({ user: null, isLoading: false })
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
    expect(useUserStore.getState()).toMatchObject({ user: null, isLoading: false })
  })
})

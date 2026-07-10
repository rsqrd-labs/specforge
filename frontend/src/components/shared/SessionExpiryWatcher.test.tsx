import { act, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

const apiMocks = vi.hoisted(() => ({
  listener: null as (() => void) | null,
}))

vi.mock("../../services/api", () => ({
  onSessionExpired: (listener: () => void) => {
    apiMocks.listener = listener
    return () => {
      apiMocks.listener = null
    }
  },
}))

const userStoreMocks = vi.hoisted(() => ({
  user: null as { id: string } | null,
  clearUser: vi.fn(),
}))

vi.mock("../../store/userStore", () => ({
  useUserStore: Object.assign(
    (selector: (state: typeof userStoreMocks) => unknown) => selector(userStoreMocks),
    { getState: () => userStoreMocks },
  ),
}))

import { ActionAlertProvider } from "./ActionAlert"
import { SessionExpiryWatcher } from "./SessionExpiryWatcher"

describe("SessionExpiryWatcher", () => {
  it("clears the user and shows a single clear alert when a live session dies", () => {
    userStoreMocks.user = { id: "u1" }
    userStoreMocks.clearUser.mockClear()

    render(
      <ActionAlertProvider>
        <SessionExpiryWatcher />
      </ActionAlertProvider>,
    )

    act(() => {
      apiMocks.listener?.()
    })

    expect(userStoreMocks.clearUser).toHaveBeenCalledTimes(1)
    expect(screen.getByText("Session expired")).toBeInTheDocument()
    expect(
      screen.getByText(
        "You were signed out because your session expired. Please sign in again to continue.",
      ),
    ).toBeInTheDocument()
  })

  it("does not show a false alarm for a guest who never had a session", () => {
    userStoreMocks.user = null
    userStoreMocks.clearUser.mockClear()

    render(
      <ActionAlertProvider>
        <SessionExpiryWatcher />
      </ActionAlertProvider>,
    )

    act(() => {
      apiMocks.listener?.()
    })

    // clearUser(null -> null) is a harmless no-op, but no alert should fire —
    // there was nothing for this visitor to lose.
    expect(userStoreMocks.clearUser).toHaveBeenCalledTimes(1)
    expect(screen.queryByText("Session expired")).not.toBeInTheDocument()
  })
})

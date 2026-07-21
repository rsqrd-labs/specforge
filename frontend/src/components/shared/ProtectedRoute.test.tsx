import { act, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useUserStore } from "../../store/userStore"
import { ProtectedRoute } from "./ProtectedRoute"

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <div>protected content</div>
            </ProtectedRoute>
          }
        />
        <Route path="/" element={<div>signed out</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe("ProtectedRoute session boundary", () => {
  beforeEach(() => {
    useUserStore.setState({ user: null, isLoading: false })
  })

  it("probes once, shows the fallback loader, and redirects a guest", async () => {
    let finish!: () => void
    const fetchMe = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    useUserStore.setState({ fetchMe })

    renderRoute()
    expect(screen.getByRole("status")).toBeInTheDocument()
    expect(fetchMe).toHaveBeenCalledTimes(1)

    await act(async () => finish())
    expect(await screen.findByText("signed out")).toBeInTheDocument()
  })

  it("renders an existing session without probing and redirects if it later expires", async () => {
    const fetchMe = vi.fn().mockResolvedValue(undefined)
    useUserStore.setState({
      user: {
        id: "u1",
        email: "user@example.com",
        google_id: "google-u1",
        name: "User",
        avatar_url: null,
        credit_balance: 50,
        created_at: "2026-07-21T00:00:00Z",
      },
      isLoading: false,
      fetchMe,
    })
    renderRoute()
    expect(screen.getByText("protected content")).toBeInTheDocument()
    expect(fetchMe).not.toHaveBeenCalled()

    act(() => useUserStore.setState({ user: null }))
    await waitFor(() => expect(screen.getByText("signed out")).toBeInTheDocument())
    expect(fetchMe).not.toHaveBeenCalled()
  })

  it("keeps content gated while the store is loading", () => {
    useUserStore.setState({
      isLoading: true,
      fetchMe: vi.fn(() => new Promise<void>(() => undefined)),
    })
    renderRoute()
    expect(screen.getByRole("status")).toBeInTheDocument()
    expect(screen.queryByText("protected content")).toBeNull()
  })
})

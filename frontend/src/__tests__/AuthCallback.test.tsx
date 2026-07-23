import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AuthCallback from "../pages/AuthCallback"
import { completeGoogleCallback, setAccessToken } from "../services/api"
import { useUserStore } from "../store/userStore"

vi.mock("../services/api", () => ({
  completeGoogleCallback: vi.fn(),
  setAccessToken: vi.fn(),
}))

describe("AuthCallback", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useUserStore.setState({
      user: null,
      isLoading: false,
      fetchMe: vi.fn().mockResolvedValue(undefined),
    })
  })

  it("exchanges the Google code and redirects to the dashboard", async () => {
    vi.mocked(completeGoogleCallback).mockResolvedValue({
      access_token: "access-token",
    })

    render(
      <MemoryRouter
        initialEntries={["/auth/callback?code=google-code&state=test-state"]}
      >
        <Routes>
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/dashboard" element={<div>Dashboard loaded</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(completeGoogleCallback).toHaveBeenCalledWith(
        "google-code",
        "test-state",
      )
    })
    expect(setAccessToken).toHaveBeenCalledWith("access-token")
    expect(await screen.findByText("Dashboard loaded")).toBeInTheDocument()
  })

  it("shows the squirrel brand lockup on callback errors", async () => {
    render(
      <MemoryRouter initialEntries={["/auth/callback"]}>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallback />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole("img", { name: "Thought2Build" })).toBeInTheDocument()
    expect(screen.queryByText("SF")).toBeNull()
    expect(await screen.findByText(/google did not return/i)).toBeInTheDocument()
  })

  it("surfaces a cancelled consent flow and lets the user return home", async () => {
    render(
      <MemoryRouter initialEntries={["/auth/callback?error=access_denied"]}>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/" element={<div>Home loaded</div>} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText(/cancelled/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /back to home/i }))
    expect(await screen.findByText("Home loaded")).toBeInTheDocument()
    expect(completeGoogleCallback).not.toHaveBeenCalled()
  })

  it("shows a recoverable error when the callback exchange fails", async () => {
    vi.mocked(completeGoogleCallback).mockRejectedValue(new Error("exchange failed"))
    render(
      <MemoryRouter initialEntries={["/auth/callback?code=bad&state=state"]}>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallback />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText(/could not finish sign-in/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument()
    expect(setAccessToken).not.toHaveBeenCalled()
  })
})

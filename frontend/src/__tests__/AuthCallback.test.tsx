import { render, screen, waitFor } from "@testing-library/react"
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
})

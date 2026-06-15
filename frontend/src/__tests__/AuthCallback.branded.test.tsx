import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Force the dark-launched flag ON for this file only.
vi.mock("../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: true },
}))

vi.mock("../services/api", () => ({
  completeGoogleCallback: vi.fn(),
  setAccessToken: vi.fn(),
}))

import AuthCallback from "../pages/AuthCallback"
import { completeGoogleCallback } from "../services/api"
import { useUserStore } from "../store/userStore"

describe("AuthCallback with branded_loaders enabled", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useUserStore.setState({
      user: null,
      isLoading: false,
      fetchMe: vi.fn().mockResolvedValue(undefined),
    })
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      media: "",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as typeof window.matchMedia
  })

  it("shows the decorative branded mark while loading without nesting a live region", async () => {
    // Keep the exchange pending so the view stays in the loading state.
    vi.mocked(completeGoogleCallback).mockReturnValue(new Promise(() => {}))

    const { container } = render(
      <MemoryRouter
        initialEntries={["/auth/callback?code=google-code&state=test-state"]}
      >
        <Routes>
          <Route path="/auth/callback" element={<AuthCallback />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(completeGoogleCallback).toHaveBeenCalled())

    // The branded mark is mounted in place of the orbit while loading.
    expect(container.querySelector(".brand-loader--overlay")).not.toBeNull()
    // The panel <section> already owns the aria-live region; the decorative
    // overlay variant must not add a nested role="status".
    expect(screen.queryByRole("status")).toBeNull()
  })
})

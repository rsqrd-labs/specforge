import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Force the dark-launched flag ON for this file only.
vi.mock("../../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: true },
}))

// Hold the route in its loading branch deterministically (isLoading true).
vi.mock("../../store/userStore", () => ({
  useUserStore: () => ({
    user: null,
    isLoading: true,
    fetchMe: vi.fn().mockResolvedValue(undefined),
  }),
}))

import { ProtectedRoute } from "./ProtectedRoute"

describe("ProtectedRoute with branded_loaders enabled", () => {
  beforeEach(() => {
    // BrandLoader reads matchMedia; jsdom lacks it.
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

  it("renders the branded block loader while the session is being checked", () => {
    const { container } = render(
      <MemoryRouter>
        <ProtectedRoute>
          <div>protected content</div>
        </ProtectedRoute>
      </MemoryRouter>,
    )

    // The branded block loader replaces the bespoke Tailwind spinner.
    expect(container.querySelector(".brand-loader--block")).not.toBeNull()
    expect(container.querySelector(".animate-spin")).toBeNull()

    // It owns its own polite live region and protected content is gated.
    expect(screen.getByRole("status")).toBeInTheDocument()
    expect(screen.queryByText("protected content")).not.toBeInTheDocument()
  })
})

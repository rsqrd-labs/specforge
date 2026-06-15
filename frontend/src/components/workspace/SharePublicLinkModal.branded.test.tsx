import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Force the dark-launched flag ON for this file only.
vi.mock("../../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: true },
}))

// Keep the modal pinned in its `loading` state by never resolving the enable
// call, so we can assert the branded inline loader is rendered for it.
vi.mock("../../services/api", () => ({
  enablePublicShare: vi.fn(() => new Promise(() => {})),
  disablePublicShare: vi.fn(() => new Promise(() => {})),
  rotatePublicShare: vi.fn(() => new Promise(() => {})),
  getApiErrorMessage: (e: unknown) => String(e),
}))

import { SharePublicLinkModal } from "./SharePublicLinkModal"

describe("SharePublicLinkModal with branded_loaders enabled", () => {
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

  it("renders the branded inline loader while a share action is in flight", async () => {
    const user = userEvent.setup()
    const { container } = render(
      <SharePublicLinkModal
        workspaceId="workspace-1"
        initialEnabled={false}
        initialSlug={null}
        onClose={vi.fn()}
      />,
    )

    // Kick off the (never-resolving) enable call to enter the loading state.
    await user.click(screen.getByRole("button", { name: /enable|publish|create/i }))

    // The branded inline loader replaces the bespoke "Working…" paragraph and
    // owns its own polite live region (no ancestor aria-live in the dialog body).
    expect(container.querySelector(".brand-loader--inline")).not.toBeNull()
    expect(container.querySelector(".share-modal-loading")).toBeNull()
    expect(screen.getByRole("status")).toBeInTheDocument()
  })
})

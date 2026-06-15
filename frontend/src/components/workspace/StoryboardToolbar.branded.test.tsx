import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Force the dark-launched flag ON for this file only. Default-off behavior is
// covered in the sibling StoryboardToolbar.test.tsx.
vi.mock("../../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: true },
}))

import { StoryboardToolbar } from "./StoryboardToolbar"
import type { StoryboardSummary } from "../../types/storyboard"

function makeStoryboard(
  overrides: Partial<StoryboardSummary> = {},
): StoryboardSummary {
  return {
    id: "storyboard-1",
    workspace_id: "workspace-1",
    version: 2,
    status: "generating",
    title: "Launch Storyboard",
    theme: "Indica",
    public_share_enabled: false,
    public_share_slug: null,
    created_at: "2026-05-30T00:00:00Z",
    updated_at: "2026-05-30T00:00:00Z",
    ...overrides,
  }
}

function renderToolbar(storyboard = makeStoryboard()) {
  return render(
    <StoryboardToolbar
      storyboard={storyboard}
      onOpen={vi.fn()}
      onPresent={vi.fn()}
      onShare={vi.fn()}
      onDownload={vi.fn()}
      onRegenerate={vi.fn()}
      onDownloadNotes={vi.fn()}
    />,
  )
}

describe("StoryboardToolbar with branded_loaders enabled", () => {
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

  it("embeds the decorative branded mark while generating without nesting live regions", () => {
    const { container } = renderToolbar()

    // The progress row already owns the only live region. The embedded
    // BrandLoader is decorative (overlay variant), so it must not add a second.
    expect(screen.getAllByRole("status")).toHaveLength(1)

    // The branded mark replaces the bespoke spinner.
    expect(container.querySelector(".brand-loader--overlay")).not.toBeNull()
    expect(container.querySelector(".storyboard-generating-spinner")).toBeNull()

    // The progress track and copy are preserved.
    expect(container.querySelector(".storyboard-generating-track")).not.toBeNull()
  })
})

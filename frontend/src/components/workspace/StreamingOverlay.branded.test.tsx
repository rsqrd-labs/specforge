import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Force the dark-launched flag ON for this file only, so we exercise the wired
// branded-loader path. The default-off behavior is covered in the sibling
// StreamingOverlay.test.tsx.
vi.mock("../../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: true },
}))

import {
  StreamingOverlay,
  type GenerationActivityInfo,
} from "./StreamingOverlay"

const activity: GenerationActivityInfo = {
  stageId: "stage-spec",
  stageType: "spec",
  operation: "generate",
  actionLabel: "generate",
  startedAt: 0,
  streamed: true,
}

describe("StreamingOverlay with branded_loaders enabled", () => {
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

  it("embeds the decorative branded mark without nesting live regions", () => {
    const { container } = render(<StreamingOverlay isVisible activity={activity} />)

    // Exactly one live region — the overlay's. The embedded BrandLoader is
    // decorative (variant="overlay"), so it must not add a second role="status".
    expect(screen.getAllByRole("status")).toHaveLength(1)

    // The branded mark replaces the generic shimmer.
    expect(container.querySelector(".brand-loader--overlay")).not.toBeNull()
    expect(container.querySelector(".generation-document-shimmer")).toBeNull()

    // The stage rail is preserved.
    expect(container.querySelector(".generation-flow-rail")).not.toBeNull()
  })
})

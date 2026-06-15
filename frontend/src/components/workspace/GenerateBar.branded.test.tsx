import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Force the dark-launched flag ON for this file only.
vi.mock("../../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: true },
}))

import { GenerateBar } from "./GenerateBar"
import type { Stage } from "../../types/stage"

function makeStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "stage-spec",
    workspace_id: "workspace-1",
    type: "spec",
    content: null,
    status: "in_progress",
    current_version: 1,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    created_at: "2026-05-30T00:00:00Z",
    updated_at: "2026-05-30T00:00:00Z",
    ...overrides,
  }
}

function renderBar(props: Partial<Parameters<typeof GenerateBar>[0]> = {}) {
  return render(
    <GenerateBar
      stage={makeStage()}
      onGenerate={vi.fn()}
      onRegenerate={vi.fn()}
      onRefine={vi.fn()}
      onFinalise={vi.fn()}
      onUnlock={vi.fn()}
      isBusy
      {...props}
    />,
  )
}

describe("GenerateBar with branded_loaders enabled", () => {
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

  it("embeds the decorative branded mark in the busy row without nesting live regions", () => {
    const { container } = renderBar()

    // The busy row already owns the only live region; the embedded BrandLoader
    // is decorative (overlay variant) and must not add a second role="status".
    expect(screen.getAllByRole("status")).toHaveLength(1)

    // The branded mark replaces the generic loading-ring.
    expect(container.querySelector(".brand-loader--overlay")).not.toBeNull()
    expect(container.querySelector(".loading-ring")).toBeNull()

    // The busy label is preserved.
    expect(screen.getByText("Generating stage...")).toBeInTheDocument()
  })
})

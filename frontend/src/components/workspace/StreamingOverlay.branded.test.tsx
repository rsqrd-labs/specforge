import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

// Force the dark-launched flag ON for this file only, so we exercise the wired
// branded-loader path. The default-off behavior is covered in the sibling
// StreamingOverlay.test.tsx.
vi.mock("../../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: true },
}))

import { useGenerationEstimatesStore } from "../../store/generationEstimatesStore"
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

  it("shows the honest ETA band alongside the stage rail (Phase 2a)", () => {
    const { container } = render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity, stageType: "plan", startedAt: Date.now() }}
      />,
    )

    // ETA band caption ("usually ~{p50}s") and the stage rail render together.
    expect(container.querySelector(".generation-flow-rail")).not.toBeNull()
    const caption = container.querySelector(".generation-eta-caption")
    expect(caption).not.toBeNull()
    expect(caption?.textContent).toMatch(/usually ~\d+s/)

    // The decorative bar must not introduce a second live region.
    expect(screen.getAllByRole("status")).toHaveLength(1)
    expect(container.querySelector(".generation-eta-bar")).toHaveAttribute(
      "aria-hidden",
      "true",
    )
  })

  it("uses the live data-backed band when present for the provider (Phase 2b)", () => {
    // Pre-populate the live store (loaded + fresh) so the hook prefers it and
    // does not fire a network fetch.
    useGenerationEstimatesStore.setState({
      status: "loaded",
      fetchedAt: Date.now(),
      estimates: [
        {
          provider: "anthropic",
          stage: "plan",
          operation: "generate",
          p50: 33,
          p90: 81,
          n: 250,
        },
      ],
    })

    const { container } = render(
      <StreamingOverlay
        isVisible
        activity={{
          ...activity,
          stageType: "plan",
          provider: "anthropic",
          startedAt: Date.now(),
        }}
      />,
    )

    // The live p50 (33s) drives the caption, not the heuristic plan baseline (45s).
    const caption = container.querySelector(".generation-eta-caption")
    expect(caption?.textContent).toMatch(/usually ~33s/)

    useGenerationEstimatesStore.setState({
      status: "idle",
      fetchedAt: null,
      estimates: [],
    })
  })

  it("names the real pipeline phase in the liveness copy (Phase 2c)", () => {
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity, startedAt: Date.now() }}
        progress={{
          stage: "spec",
          state: "generating",
          elapsed_seconds: 30,
          phase: "critic",
        }}
      />,
    )

    // The critic phase is the one long enough to actually emit heartbeats; the
    // liveness line reflects it instead of the generic "still working" copy.
    const status = screen.getByRole("status")
    expect(status).toHaveTextContent(/a reviewer model is checking the draft/i)
    expect(status).not.toHaveTextContent(/the model is working/i)
  })

  it("falls back to the generic liveness copy for an unknown phase (Phase 2c)", () => {
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity, startedAt: Date.now() }}
        progress={{
          stage: "spec",
          state: "generating",
          elapsed_seconds: 30,
          phase: "some_future_phase",
        }}
      />,
    )

    // An unknown/future phase must degrade to the generic copy, never break.
    expect(screen.getByRole("status")).toHaveTextContent(
      "the model is working; this can take several minutes.",
    )
  })
})

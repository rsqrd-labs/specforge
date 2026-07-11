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

/** An activity that started `secondsAgo` in the past, to drive the elapsed band. */
function agedActivity(
  secondsAgo: number,
  overrides: Partial<GenerationActivityInfo> = {},
): GenerationActivityInfo {
  return { ...activity, startedAt: Date.now() - secondsAgo * 1000, ...overrides }
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

  it("embeds the decorative branded mark and the slim macro stage rail", () => {
    const { container } = render(<StreamingOverlay isVisible activity={activity} />)

    // Exactly one live region — the overlay's. The embedded BrandLoader is
    // decorative (variant="overlay"), so it must not add a second role="status".
    expect(screen.getAllByRole("status")).toHaveLength(1)

    // The branded mark replaces the generic shimmer.
    expect(container.querySelector(".brand-loader--overlay")).not.toBeNull()
    expect(container.querySelector(".generation-document-shimmer")).toBeNull()

    // The slim macro stage rail is present; the legacy trace bar is gone.
    expect(container.querySelector(".generation-stage-rail")).not.toBeNull()
    expect(container.querySelector(".generation-trace")).toBeNull()
  })

  it("shows a phase stepper and NO numeric time caption on the heuristic path", () => {
    const { container } = render(
      <StreamingOverlay isVisible activity={agedActivity(0, { stageType: "plan" })} />,
    )

    // The phase stepper replaces the synthetic ETA bar as the primary signal.
    expect(container.querySelector(".generation-phase-steps")).not.toBeNull()
    // No decelerating bar and no false-precision "~30s" / "usually" caption.
    expect(container.querySelector(".generation-eta-bar")).toBeNull()
    const status = screen.getByRole("status")
    expect(status).not.toHaveTextContent(/usually/i)
    expect(status).not.toHaveTextContent(/~\d+s/)
    // The card is aria-hidden so its per-second elapsed never reaches AT.
    expect(container.querySelector(".generation-loading-card")).toHaveAttribute(
      "aria-hidden",
      "true",
    )
  })

  it("keeps the typical band silent, then escalates reassurance by band", () => {
    // Typical (elapsed 0 < spec p90 75): no time language at all.
    const typical = render(<StreamingOverlay isVisible activity={agedActivity(0)} />)
    expect(
      typical.container.querySelector(".generation-reassurance"),
    ).toBeNull()
    typical.unmount()

    // Overdue (75 ≤ elapsed < 180): "a little longer than usual".
    const overdue = render(<StreamingOverlay isVisible activity={agedActivity(100)} />)
    const overdueStatus = overdue.container.querySelector(
      ".generation-loading-status",
    )
    expect(overdueStatus).toHaveClass("is-overdue")
    expect(overdueStatus).toHaveTextContent(/a little longer than usual/i)
    overdue.unmount()

    // Long (≥ 180s): concrete multi-minute reassurance.
    const long = render(<StreamingOverlay isVisible activity={agedActivity(200)} />)
    const longStatus = long.container.querySelector(".generation-loading-status")
    expect(longStatus).toHaveClass("is-long")
    expect(longStatus).toHaveTextContent(/can take a few minutes/i)
  })

  it("shows a live-data upper bound (never a median) when real data exists", () => {
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
        activity={agedActivity(0, { stageType: "plan", provider: "anthropic" })}
      />,
    )

    // The live p90 (81s) drives a rounded-up upper bound — no lower anchor, no
    // p50 (33s), no "~30s"-style median.
    const bound = container.querySelector(".generation-eta-bound")
    expect(bound).not.toBeNull()
    expect(bound?.textContent).toBe("usually under ~2 min")
    expect(bound?.textContent).not.toMatch(/33/)

    useGenerationEstimatesStore.setState({
      status: "idle",
      fetchedAt: null,
      estimates: [],
    })
  })

  it("advances the phase stepper to the real backend phase", () => {
    const { container } = render(
      <StreamingOverlay
        isVisible
        activity={agedActivity(0)}
        progress={{ stage: "spec", state: "generating", elapsed_seconds: 30, phase: "critic" }}
      />,
    )

    // The critic phase maps to the Reviewer step, which becomes active.
    const active = container.querySelector(".generation-phase-step.is-active")
    expect(active).toHaveTextContent("Reviewer")

    // The single live region announces the current step (not a per-second tick).
    expect(screen.getByRole("status")).toHaveTextContent(
      /a reviewer model is checking the draft/i,
    )
  })

  it("holds the stepper at Drafting for an unknown / future phase", () => {
    const { container } = render(
      <StreamingOverlay
        isVisible
        activity={agedActivity(0)}
        progress={{
          stage: "spec",
          state: "generating",
          elapsed_seconds: 30,
          phase: "some_future_phase",
        }}
      />,
    )

    const active = container.querySelector(".generation-phase-step.is-active")
    expect(active).toHaveTextContent("Drafting")
    expect(screen.getByRole("status")).not.toHaveTextContent(/reviewer model/i)
  })
})

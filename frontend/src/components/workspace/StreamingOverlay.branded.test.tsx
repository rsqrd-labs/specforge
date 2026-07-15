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

    // The round shape is now the progress ring, seating the mark inside it.
    expect(container.querySelector(".generation-phase-ring")).not.toBeNull()
    expect(
      container.querySelectorAll(".generation-phase-ring .generation-ring-seg"),
    ).toHaveLength(5)
  })

  it("shows the phase ring and NO numeric time caption on the heuristic path", () => {
    const { container } = render(
      <StreamingOverlay isVisible activity={agedActivity(0, { stageType: "plan" })} />,
    )

    // The phase ring replaces the synthetic ETA bar as the primary signal.
    expect(container.querySelector(".generation-phase-ring")).not.toBeNull()
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
        activity={agedActivity(0, { stageType: "plan" })}
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

  it("advances the phase ring to the real backend phase", () => {
    const { container } = render(
      <StreamingOverlay
        isVisible
        activity={agedActivity(0)}
        progress={{ stage: "spec", state: "generating", elapsed_seconds: 30, phase: "critic" }}
      />,
    )

    // The critic phase maps to the Reviewer step (index 3), whose arc is active.
    const segs = Array.from(container.querySelectorAll(".generation-ring-seg"))
    expect(segs[3]).toHaveClass("is-active")
    // The one-line phase status names the current step + count.
    expect(container.querySelector(".generation-phase-line")).toHaveTextContent(
      /Reviewer — step 4 of 5/i,
    )

    // The single live region announces the current step (not a per-second tick).
    expect(screen.getByRole("status")).toHaveTextContent(
      /a reviewer model is checking the draft/i,
    )
  })

  it("holds the ring at Drafting for an unknown / future phase", () => {
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

    const segs = Array.from(container.querySelectorAll(".generation-ring-seg"))
    expect(segs[0]).toHaveClass("is-active")
    expect(screen.getByRole("status")).not.toHaveTextContent(/reviewer model/i)
  })

  it("marks a jumped-over Reviewer step as skipped, never complete (issue #34)", () => {
    // Default async-advisory path: phase hops quality_gate → persisting, so the
    // Reviewer step (index 3) never runs on the critical path. Its arc must stay
    // hollow (skipped), not draw a filled check for work that ran detached.
    const { container, rerender } = render(
      <StreamingOverlay
        isVisible
        activity={agedActivity(0)}
        progress={{ stage: "spec", state: "generating", elapsed_seconds: 5, phase: "quality_gate" }}
      />,
    )
    rerender(
      <StreamingOverlay
        isVisible
        activity={agedActivity(0)}
        progress={{ stage: "spec", state: "generating", elapsed_seconds: 10, phase: "persisting" }}
      />,
    )

    const segs = Array.from(container.querySelectorAll(".generation-ring-seg"))
    // Reviewer (3): jumped over → skipped, not complete.
    expect(segs[3]).toHaveClass("is-skipped")
    expect(segs[3]).not.toHaveClass("is-complete")
    // Quality checks (2) was observed → complete; Saving (4) is now active.
    expect(segs[2]).toHaveClass("is-complete")
    expect(segs[4]).toHaveClass("is-active")
  })
})

import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AI_DISCLAIMER_COPY } from "../shared/AiDisclaimer"
import {
  applySlideFitStep,
  MAX_SLIDE_FIT_STEP,
  StoryboardDeck,
  STORYBOARD_ACTS,
} from "./StoryboardDeck"
import {
  makeMaxCapStoryboardPayload,
  MAX_CAP_HEADLINE,
  MAX_CAP_VISIBLE_TEXT,
} from "./testPayload"
import type {
  StoryboardDiagramLayer,
  StoryboardLayerKind,
  StoryboardPayload,
  StoryboardSectionTitle,
} from "../../types/storyboard"

function layer(kind: StoryboardLayerKind): StoryboardDiagramLayer {
  return {
    id: `${kind}-layer`,
    kind,
    label: `${kind} label`,
    summary: `${kind} summary`,
    source_refs: [
      {
        source: "PLAN",
        source_id: `${kind}-source`,
        excerpt: `${kind} excerpt`,
      },
    ],
  }
}

function slideId(title: StoryboardSectionTitle): string {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

function makePayload(): StoryboardPayload {
  return {
    title: "Thought2Build Launch",
    theme: {
      palette: ["#8f4e00", "#a1385f", "#565e74"],
      typography: "Confident product sans",
      motif: "Copper circuit cards",
      transition_style: "Measured reveal",
      diagram_style: "Layered architecture cards",
    },
    sections: STORYBOARD_ACTS.map((title) => {
      const id = slideId(title)
      return {
        id,
        title,
        slides: [
          {
            id: `${id}-slide`,
            type: title === "Technical Architecture" ? "architecture" : "hero",
            headline: `${title} headline`,
            visible_text: `${title} visible text`,
            visual: { kind: "video-demo" },
            speaker_notes_ref: `${id}-slide`,
            sources: ["SPEC", "PLAN"],
          },
        ],
      }
    }),
    diagrams: [
      {
        id: "architecture-reveal",
        type: "architecture_reveal",
        layers: [
          layer("client"),
          layer("frontend"),
          layer("api"),
          layer("data"),
          layer("llm"),
          layer("integrations"),
          layer("trust"),
          layer("recovery"),
        ],
      },
    ],
    source_map: {
      "opening-thesis-slide": [
        {
          source: "SPEC",
          source_id: "spec-1",
          excerpt: "Bounded source excerpt",
        },
      ],
    },
    notes: Object.fromEntries(
      STORYBOARD_ACTS.map((title) => {
        const id = `${slideId(title)}-slide`
        return [
          id,
          {
            slide_id: id,
            talk_track: `${title} talk track`,
            transition: `${title} transition`,
            timing_seconds: 45,
            pause_cue: "Pause for emphasis",
            demo_cue: "Show the product path",
            backup_points: ["Backup point"],
          },
        ]
      }),
    ),
    demo_script_md: "## Demo",
    technical_appendix_md: "## Appendix",
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("StoryboardDeck", () => {
  it("renders exactly six top-level acts from the payload", () => {
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)

    const tabs = screen.getAllByRole("tab")
    expect(tabs).toHaveLength(6)
    expect(tabs.map((tab) => tab.textContent?.replace(/^\d+/, ""))).toEqual(
      STORYBOARD_ACTS,
    )
    expect(screen.getByText("Opening Thesis headline")).toBeInTheDocument()
    expect(screen.getByText(AI_DISCLAIMER_COPY)).toBeInTheDocument()
  })

  it("supports keyboard navigation and fullscreen shortcut", async () => {
    const requestFullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
    })
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)

    fireEvent.keyDown(window, { key: "ArrowRight" })
    expect(screen.getByText("Product Vision headline")).toBeInTheDocument()

    fireEvent.keyDown(window, { key: " ", code: "Space" })
    expect(screen.getByText("Product Walkthrough headline")).toBeInTheDocument()

    fireEvent.keyDown(window, { key: "ArrowLeft" })
    expect(screen.getByText("Product Vision headline")).toBeInTheDocument()

    await act(async () => {
      fireEvent.keyDown(window, { key: "f" })
    })
    expect(requestFullscreen).toHaveBeenCalledOnce()
  })

  it("toggles presenter mode and source layer only when allowed", () => {
    const { rerender } = render(
      <StoryboardDeck payload={makePayload()} status="ready" isOwner />,
    )

    fireEvent.keyDown(window, { key: "p" })
    expect(screen.getByLabelText(/presenter mode/i)).toHaveTextContent(
      /opening thesis talk track/i,
    )

    fireEvent.keyDown(window, { key: "s" })
    expect(screen.getByLabelText(/source layer/i)).toHaveTextContent(/SPEC/)

    rerender(
      <StoryboardDeck
        payload={makePayload()}
        status="ready"
        isOwner={false}
        allowPresenterMode={false}
        allowSourceLayer={false}
      />,
    )

    fireEvent.keyDown(window, { key: "p" })
    fireEvent.keyDown(window, { key: "s" })
    expect(screen.queryByLabelText(/presenter mode/i)).toBeNull()
    expect(screen.queryByLabelText(/source layer/i)).toBeNull()
  })

  it("renders architecture reveal on the technical architecture act", () => {
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)

    fireEvent.click(screen.getByRole("tab", { name: /technical architecture/i }))

    const reveal = screen.getByLabelText("Technical Architecture")
    expect(within(reveal).getByText(/architecture layers revealed/i)).toBeInTheDocument()
    expect(within(reveal).getByText(/8 of 8 architecture layers/i)).toBeInTheDocument()
    expect(screen.getByText("Technical Architecture headline")).toBeInTheDocument()
  })

  it("renders a deterministic themed visual, never a media promise or raw source text", () => {
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)

    // No media promise is honoured, and raw source-artifact excerpts never leak
    // onto the hero visual (they live in the toggleable Sources layer).
    expect(screen.queryByText(/video-demo/i)).toBeNull()
    expect(screen.queryByText(/bounded source excerpt/i)).toBeNull()
    expect(screen.queryByText(/spec-1/i)).toBeNull()
    // The deterministic frame is a themed visual with a kind label; the headline
    // stays in the slide copy (not duplicated into the visual).
    expect(screen.getByText("Highlight")).toBeInTheDocument()
    expect(screen.getByText("Opening Thesis headline")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: /product walkthrough/i }))
    expect(screen.getAllByText(/product walkthrough visible text/i).length).toBeGreaterThan(0)
  })

  it("handles loading, error, empty, failed, stale, and not-found states", () => {
    const { rerender } = render(<StoryboardDeck isLoading title="Storyboard" />)
    expect(screen.getByText(/loading storyboard/i)).toBeInTheDocument()

    rerender(<StoryboardDeck errorMessage="Boom" title="Storyboard" />)
    expect(screen.getByText("Boom")).toBeInTheDocument()

    rerender(<StoryboardDeck isNotFound title="Storyboard" />)
    expect(screen.getByText(/storyboard not found/i)).toBeInTheDocument()

    rerender(<StoryboardDeck payload={null} status="ready" />)
    expect(screen.getByText(/storyboard is empty/i)).toBeInTheDocument()

    rerender(<StoryboardDeck payload={makePayload()} status="failed" />)
    expect(screen.getByText(/credits were refunded/i)).toBeInTheDocument()

    rerender(<StoryboardDeck payload={makePayload()} status="stale" isOwner />)
    expect(screen.getByText(/stale storyboard/i)).toBeInTheDocument()
  })

  it("frames the first slide as the deck cover with a centred feature layout", () => {
    const { container } = render(
      <StoryboardDeck payload={makePayload()} status="ready" isOwner />,
    )
    const slide = container.querySelector(".storyboard-slide")
    expect(slide?.className).toContain("storyboard-slide--cover")
    expect(slide?.className).toContain("storyboard-slide--layout-feature")
    expect(container.querySelector(".storyboard-slide-cover-mark")?.textContent).toBe(
      "Thought2Build Launch",
    )
  })

  it("gives the first slide of each act the act-intro label", () => {
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)
    expect(screen.getByText(/act 1 of 6/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: /technical architecture/i }))
    expect(screen.getByText(/act 4 of 6/i)).toBeInTheDocument()
  })

  it("makes the architecture slide full-bleed, not the split visual panel", () => {
    const { container } = render(
      <StoryboardDeck payload={makePayload()} status="ready" isOwner />,
    )
    fireEvent.click(screen.getByRole("tab", { name: /technical architecture/i }))
    const slide = container.querySelector(".storyboard-slide")
    expect(slide?.className).toContain("storyboard-slide--layout-arch")
    expect(slide?.className).toContain("storyboard-slide--arch")
  })

  it("uses the split layout for interior product slides and a giant figure for metric visuals", () => {
    const payload = makePayload()
    const visionIndex = payload.sections.findIndex(
      (section) => section.title === "Product Vision",
    )
    const base = payload.sections[visionIndex].slides[0]
    payload.sections[visionIndex].slides = [
      {
        ...base,
        id: "pv-split",
        type: "product",
        visual: { kind: "bullets", points: ["Alpha", "Beta"] },
      },
      {
        ...base,
        id: "pv-metric",
        type: "product",
        visual: { kind: "metric", value: "99.9%", label: "uptime" },
      },
    ]

    const { container } = render(
      <StoryboardDeck payload={payload} status="ready" isOwner />,
    )
    fireEvent.click(screen.getByRole("tab", { name: /product vision/i }))
    let slide = container.querySelector(".storyboard-slide")
    expect(slide?.className).toContain("storyboard-slide--layout-split")
    expect(slide?.className).toContain("storyboard-slide--act-open")

    // The second slide of the act is a metric figure and no longer act-opening.
    fireEvent.keyDown(window, { key: "ArrowRight" })
    slide = container.querySelector(".storyboard-slide")
    expect(slide?.className).toContain("storyboard-slide--layout-metric")
    expect(slide?.className).not.toContain("storyboard-slide--act-open")
  })

  it("keeps SPEC/PLAN/HARNESS/TASKS citations off the slide surface", () => {
    const { container } = render(
      <StoryboardDeck payload={makePayload()} status="ready" isOwner />,
    )

    // The audience surface carries no source badges: a launch keynote must not
    // read like an audit trail. `slide.sources` stays in the payload — it feeds
    // the SourceLayer overlay, which remains the evidence surface.
    expect(container.querySelector(".storyboard-slide-source-badges")).toBeNull()
    const slide = container.querySelector(".storyboard-slide")
    expect(slide?.textContent).not.toMatch(/\b(SPEC|PLAN|HARNESS|TASKS)\b/)

    fireEvent.keyDown(window, { key: "s" })
    expect(screen.getByLabelText(/source layer/i)).toHaveTextContent(/SPEC/)
  })

  it("renders the max-cap fixture without badges and with the autofit hook armed", () => {
    const payload = makeMaxCapStoryboardPayload()
    const { container } = render(
      <StoryboardDeck payload={payload} status="ready" isOwner />,
    )

    expect(screen.getAllByText(MAX_CAP_HEADLINE).length).toBeGreaterThan(0)
    expect(screen.getAllByText(MAX_CAP_VISIBLE_TEXT).length).toBeGreaterThan(0)

    const slide = container.querySelector(".storyboard-slide")
    // jsdom reports zero heights, so the measured deck never overflows here; the
    // attribute proves the deterministic autofit pass ran on mount.
    expect(slide?.getAttribute("data-fit-step")).toBe("0")
    expect(slide?.textContent).not.toMatch(/\b(SPEC|PLAN|HARNESS|TASKS)\b/)

    // Navigation across a two-slides-per-act deck stays coherent.
    fireEvent.keyDown(window, { key: "ArrowRight" })
    expect(container.querySelector(".storyboard-slide--layout-metric")).not.toBeNull()
  })

  it("fixture strings sit exactly at the generation-schema maxima", () => {
    expect(MAX_CAP_HEADLINE).toHaveLength(140)
    expect(MAX_CAP_HEADLINE.split(" ")).toHaveLength(18)
    expect(MAX_CAP_VISIBLE_TEXT.length).toBeLessThanOrEqual(360)
    expect(MAX_CAP_VISIBLE_TEXT.split(" ")).toHaveLength(45)
  })

  it("keeps generated deck details in memory while shortcuts are used", () => {
    const localSpy = vi.spyOn(Storage.prototype, "setItem")
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)

    fireEvent.keyDown(window, { key: "ArrowRight" })
    fireEvent.keyDown(window, { key: "p" })
    fireEvent.keyDown(window, { key: "s" })

    expect(localSpy).not.toHaveBeenCalled()
  })
})

describe("applySlideFitStep", () => {
  // A fake element whose scrollHeight readings advance per fit step, mirroring
  // how shrinking the type scale reduces content height in a real layout.
  function fakeSlide(clientHeight: number, scrollHeightPerStep: number[]) {
    let step = 0
    const attributes: Record<string, string> = {}
    return {
      attributes,
      get scrollHeight() {
        return scrollHeightPerStep[Math.min(step, scrollHeightPerStep.length - 1)]
      },
      clientHeight,
      setAttribute(name: string, value: string) {
        attributes[name] = value
        if (name === "data-fit-step") step = Number(value)
      },
    }
  }

  it("leaves a fitting slide at step 0", () => {
    const slide = fakeSlide(600, [480])
    expect(applySlideFitStep(slide)).toBe(0)
    expect(slide.attributes["data-fit-step"]).toBe("0")
  })

  it("steps down only until the slide fits", () => {
    const slide = fakeSlide(600, [800, 700, 560])
    expect(applySlideFitStep(slide)).toBe(2)
    expect(slide.attributes["data-fit-step"]).toBe("2")
  })

  it("caps at the last step and lets the overflow safety net scroll the rest", () => {
    const slide = fakeSlide(600, [2000, 1900, 1800, 1700])
    expect(applySlideFitStep(slide)).toBe(MAX_SLIDE_FIT_STEP)
    expect(slide.attributes["data-fit-step"]).toBe(String(MAX_SLIDE_FIT_STEP))
  })

  it("treats sub-pixel overshoot as fitting", () => {
    const slide = fakeSlide(600, [601])
    expect(applySlideFitStep(slide)).toBe(0)
  })
})

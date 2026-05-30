import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { StoryboardDeck, STORYBOARD_ACTS } from "./StoryboardDeck"
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
    title: "SpecForge Launch",
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

  it("uses deterministic visual frames instead of generated media promises", () => {
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)

    expect(screen.queryByText(/video-demo/i)).toBeNull()
    expect(screen.getByText(/spec-1/i)).toBeInTheDocument()
    expect(screen.getByText(/bounded source excerpt/i)).toBeInTheDocument()

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

  it("keeps generated deck details in memory while shortcuts are used", () => {
    const localSpy = vi.spyOn(Storage.prototype, "setItem")
    render(<StoryboardDeck payload={makePayload()} status="ready" isOwner />)

    fireEvent.keyDown(window, { key: "ArrowRight" })
    fireEvent.keyDown(window, { key: "p" })
    fireEvent.keyDown(window, { key: "s" })

    expect(localSpy).not.toHaveBeenCalled()
  })
})

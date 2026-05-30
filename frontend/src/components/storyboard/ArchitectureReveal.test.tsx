import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  ARCHITECTURE_LAYER_SEQUENCE,
  ArchitectureReveal,
  orderArchitectureLayers,
} from "./ArchitectureReveal"
import type { StoryboardDiagramLayer, StoryboardLayerKind } from "../../types/storyboard"

function makeLayer(kind: StoryboardLayerKind, label = kind): StoryboardDiagramLayer {
  return {
    id: `${kind}-layer`,
    kind,
    label: `${label} layer`,
    summary: `${label} summary`,
    source_refs: [
      {
        source: "SPEC",
        source_id: `${kind}-source`,
        excerpt: `${label} excerpt`,
      },
    ],
  }
}

describe("ArchitectureReveal", () => {
  it("renders all required architecture layers in deterministic order", () => {
    const shuffled = [
      makeLayer("recovery"),
      makeLayer("client"),
      makeLayer("trust"),
      makeLayer("frontend"),
      makeLayer("integrations"),
      makeLayer("api"),
      makeLayer("llm"),
      makeLayer("data"),
    ]

    expect(orderArchitectureLayers(shuffled).map((layer) => layer.kind)).toEqual(
      ARCHITECTURE_LAYER_SEQUENCE,
    )

    const { container } = render(<ArchitectureReveal layers={shuffled} />)
    const fallback = screen.getByLabelText(/ordered fallback summary/i)
    const items = within(fallback).getAllByRole("listitem")

    expect(items.map((item) => item.getAttribute("data-layer-kind"))).toEqual(
      ARCHITECTURE_LAYER_SEQUENCE,
    )
    expect(container.querySelector("canvas")).toBeNull()
  })

  it("reveals steps while keeping the screen reader and PDF fallback complete", () => {
    const layers = ARCHITECTURE_LAYER_SEQUENCE.map((kind) => makeLayer(kind))

    render(<ArchitectureReveal layers={layers} currentStep={3} />)

    expect(
      screen.getByText(/3 of 8 architecture layers revealed/i),
    ).toBeInTheDocument()

    const fallback = screen.getByLabelText(/ordered fallback summary/i)
    expect(within(fallback).getAllByRole("listitem")).toHaveLength(8)
    expect(within(fallback).getByText(/client layer/i)).toBeInTheDocument()
    expect(within(fallback).getByText(/recovery layer/i)).toBeInTheDocument()
  })
})

import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  ARCHITECTURE_LAYER_SEQUENCE,
  ArchitectureReveal,
  orderArchitectureLayers,
} from "./ArchitectureReveal"
import type { StoryboardDiagramLayer, StoryboardLayerKind } from "../../types/storyboard"

// The six connectable box nodes and the five canonical edges the topology graph
// always draws (trust + recovery are overlay regions, not boxes).
const BOX_KINDS = ["client", "frontend", "api", "data", "llm", "integrations"] as const
const CANONICAL_EDGES = [
  "client-frontend",
  "frontend-api",
  "api-data",
  "api-llm",
  "api-integrations",
] as const

function makeLayer(kind: StoryboardLayerKind, label: string = kind): StoryboardDiagramLayer {
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

function allLayers(): StoryboardDiagramLayer[] {
  return ARCHITECTURE_LAYER_SEQUENCE.map((kind) => makeLayer(kind))
}

describe("ArchitectureReveal", () => {
  it("orders layers deterministically and keeps the screen-reader fallback complete", () => {
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

    render(<ArchitectureReveal layers={shuffled} />)
    const fallback = screen.getByLabelText(/ordered fallback summary/i)
    const items = within(fallback).getAllByRole("listitem")
    expect(items.map((item) => item.getAttribute("data-layer-kind"))).toEqual(
      ARCHITECTURE_LAYER_SEQUENCE,
    )
  })

  it("draws the full topology: all eight planes (six nodes + two regions) and the canonical edges", () => {
    const { container } = render(<ArchitectureReveal layers={allLayers()} />)

    const nodeKinds = Array.from(container.querySelectorAll("[data-arch-node]")).map(
      (node) => node.getAttribute("data-arch-node"),
    )
    expect(nodeKinds.sort()).toEqual([...BOX_KINDS].sort())

    const edges = Array.from(container.querySelectorAll("[data-arch-edge]")).map((edge) =>
      edge.getAttribute("data-arch-edge"),
    )
    expect(edges.sort()).toEqual([...CANONICAL_EDGES].sort())

    // The trust boundary and recovery backplane are present as labelled regions.
    expect(container.querySelector(".arch-region--trust")).not.toBeNull()
    expect(container.querySelector(".arch-region--recovery")).not.toBeNull()
    expect(container.querySelector(".arch-region__label--trust")?.textContent).toContain(
      "trust",
    )
    expect(
      container.querySelector(".arch-region__label--recovery")?.textContent,
    ).toContain("recovery")

    // Inert SVG topology, not a canvas.
    expect(container.querySelector("canvas")).toBeNull()
    expect(container.querySelector("svg.architecture-topology")).not.toBeNull()
  })

  it("renders the static-complete topology regardless of step (the diagram needs no JS timers)", () => {
    // Even with a partial currentStep the full node/edge set is in the DOM — the
    // build-up is a CSS-only layer, so reduced-motion / PDF see the complete graph.
    const { container } = render(
      <ArchitectureReveal layers={allLayers()} currentStep={3} />,
    )
    expect(container.querySelectorAll("[data-arch-node]")).toHaveLength(BOX_KINDS.length)
    expect(container.querySelectorAll("[data-arch-edge]")).toHaveLength(
      CANONICAL_EDGES.length,
    )
    expect(
      screen.getByText(/3 of 8 architecture layers revealed/i),
    ).toBeInTheDocument()

    const fallback = screen.getByLabelText(/ordered fallback summary/i)
    expect(within(fallback).getAllByRole("listitem")).toHaveLength(8)
  })

  it("tolerates unknown / group layer kinds by rendering them as unconnected annotations", () => {
    const layers: StoryboardDiagramLayer[] = [
      ...allLayers(),
      makeLayer("group", "feature group"),
    ]
    const { container } = render(<ArchitectureReveal layers={layers} />)

    // The six canonical box nodes plus the one annotation node — no crash, and
    // the group kind never adds a connecting edge.
    const nodeKinds = Array.from(container.querySelectorAll("[data-arch-node]")).map(
      (node) => node.getAttribute("data-arch-node"),
    )
    expect(nodeKinds).toContain("group")
    expect(container.querySelector(".arch-node--extra")).not.toBeNull()
    expect(container.querySelectorAll("[data-arch-edge]")).toHaveLength(
      CANONICAL_EDGES.length,
    )
  })

  it("falls back to canonical copy when a plane is missing from the diagram", () => {
    // Only a client layer is supplied; the other planes must still be drawn so the
    // topology is complete.
    const { container } = render(<ArchitectureReveal layers={[makeLayer("client")]} />)
    expect(container.querySelectorAll("[data-arch-node]")).toHaveLength(BOX_KINDS.length)
    expect(container.querySelectorAll("[data-arch-edge]")).toHaveLength(
      CANONICAL_EDGES.length,
    )
  })
})

import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { AdvisoryFindingsPanel } from "./AdvisoryFindingsPanel"
import type { QualityGateFinding } from "../../types/stage"

const findings: QualityGateFinding[] = [
  { kind: "ShallowSection", detail: "The Risks section is thin.", reference: "## Risks" },
  { kind: "CoverageGap", detail: "FR-007 is unaddressed.", reference: "FR-007" },
]

describe("AdvisoryFindingsPanel", () => {
  it("renders nothing when there are no findings", () => {
    const { container } = render(
      <AdvisoryFindingsPanel findings={[]} stageType="spec" />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("frames findings as optional suggestions on a finalisable draft", () => {
    render(<AdvisoryFindingsPanel findings={findings} stageType="spec" />)

    // Never reads as a hard block.
    expect(screen.getByText(/ready/i)).toBeInTheDocument()
    expect(screen.getByRole("status")).toBeInTheDocument()
    // Plain-language kind labels, not raw critic jargon.
    expect(screen.getByText("Needs more detail")).toBeInTheDocument()
    expect(screen.getByText("Uncovered requirement")).toBeInTheDocument()
    expect(screen.getByText(/The Risks section is thin\./)).toBeInTheDocument()
  })

  it("offers a regenerate action and a non-destructive dismiss", () => {
    const onRegenerate = vi.fn()
    render(
      <AdvisoryFindingsPanel
        findings={findings}
        stageType="spec"
        onRegenerate={onRegenerate}
      />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Regenerate to address" }))
    expect(onRegenerate).toHaveBeenCalledOnce()

    // Dismiss collapses to a slim, re-expandable notice (still finalisable).
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
    expect(screen.getByText(/2 suggestions/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Show suggestions" }))
    expect(screen.getByText("Needs more detail")).toBeInTheDocument()
  })
})

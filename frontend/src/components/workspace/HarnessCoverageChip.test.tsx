import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { HarnessCoverageChip } from "./HarnessCoverageChip"

describe("HarnessCoverageChip", () => {
  it("renders nothing when coverage_summary is null", () => {
    const { container } = render(<HarnessCoverageChip coverage_summary={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when coverage_summary is undefined", () => {
    const { container } = render(
      <HarnessCoverageChip coverage_summary={undefined} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when coverage is below 100%", () => {
    const { container } = render(
      <HarnessCoverageChip
        coverage_summary={{ tests: 12, covered: 13, total: 21, percent: 62 }}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing at exactly 80%", () => {
    const { container } = render(
      <HarnessCoverageChip
        coverage_summary={{ tests: 18, covered: 17, total: 21, percent: 80 }}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("renders the full-coverage badge at 100%", () => {
    render(
      <HarnessCoverageChip
        coverage_summary={{ tests: 21, covered: 21, total: 21, percent: 100 }}
      />,
    )
    const chip = screen.getByLabelText("Full harness coverage")
    expect(chip.className).toContain("is-full")
    expect(screen.getByText("✓ Full coverage")).toBeInTheDocument()
  })
})

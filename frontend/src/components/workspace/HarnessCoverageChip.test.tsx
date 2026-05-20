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

  it("renders without warning state at 100%", () => {
    render(
      <HarnessCoverageChip
        coverage_summary={{ tests: 21, covered: 21, total: 21, percent: 100 }}
      />,
    )
    const chip = screen.getByLabelText("Harness coverage: 100%")
    expect(chip.className).toContain("harness-coverage-chip")
    expect(chip.className).not.toContain("is-warning")
  })

  it("renders the warning state below 80%", () => {
    render(
      <HarnessCoverageChip
        coverage_summary={{ tests: 12, covered: 13, total: 21, percent: 62 }}
      />,
    )
    const chip = screen.getByLabelText("Harness coverage: 62%")
    expect(chip.className).toContain("is-warning")
  })

  it("does not render the warning state at exactly 80%", () => {
    render(
      <HarnessCoverageChip
        coverage_summary={{ tests: 18, covered: 17, total: 21, percent: 80 }}
      />,
    )
    const chip = screen.getByLabelText("Harness coverage: 80%")
    expect(chip.className).not.toContain("is-warning")
  })

  it("falls back to a percent label when total is zero", () => {
    render(
      <HarnessCoverageChip
        coverage_summary={{ tests: 0, covered: 92, total: 0, percent: 92 }}
      />,
    )
    expect(screen.getByText("92%")).toBeInTheDocument()
  })
})

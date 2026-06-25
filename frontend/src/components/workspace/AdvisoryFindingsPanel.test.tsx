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

    // Defaults to the slim, non-intrusive pill so it never covers the document.
    expect(screen.getByText(/2 suggestions/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Show suggestions" }))

    // Once expanded it never reads as a hard block.
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

    // Starts collapsed now — expand to reach the actions.
    fireEvent.click(screen.getByRole("button", { name: "Show suggestions" }))

    fireEvent.click(screen.getByRole("button", { name: "Regenerate to address" }))
    expect(onRegenerate).toHaveBeenCalledOnce()

    // Dismiss collapses to a slim, re-expandable notice (still finalisable).
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
    expect(screen.getByText(/2 suggestions/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Show suggestions" }))
    expect(screen.getByText("Needs more detail")).toBeInTheDocument()
  })

  it("suppresses regenerate and reads as a note for an informational-only finding", () => {
    // Phase D: a problem-statement-condensed notice cannot be regenerated away.
    const onRegenerate = vi.fn()
    render(
      <AdvisoryFindingsPanel
        findings={[
          {
            kind: "ProblemStatementCondensed",
            detail: "Your problem statement was condensed before generating this spec.",
            reference: null,
          },
        ]}
        stageType="spec"
        onRegenerate={onRegenerate}
      />,
    )

    // Starts collapsed as a "note" pill; expand to inspect the card.
    expect(screen.getByText(/1 note/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Show notes" }))

    // No misleading "Regenerate to address" action.
    expect(
      screen.queryByRole("button", { name: "Regenerate to address" }),
    ).not.toBeInTheDocument()
    // Friendly label, not raw jargon.
    expect(screen.getByText("Condensed problem statement")).toBeInTheDocument()
    // Reads as a "note", not a "suggestion".
    expect(screen.getAllByText(/note/i).length).toBeGreaterThan(0)
    expect(screen.queryByText(/suggestion/i)).not.toBeInTheDocument()

    // Collapse still works and uses the "note" noun.
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
    expect(screen.getByText(/1 note/)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Show notes" }),
    ).toBeInTheDocument()
  })

  it("still offers regenerate when a real defect is mixed with a notice", () => {
    const onRegenerate = vi.fn()
    render(
      <AdvisoryFindingsPanel
        findings={[
          ...findings,
          {
            kind: "ProblemStatementCondensed",
            detail: "Your problem statement was condensed.",
            reference: null,
          },
        ]}
        stageType="spec"
        onRegenerate={onRegenerate}
      />,
    )
    // Starts collapsed now — expand to reach the action.
    fireEvent.click(screen.getByRole("button", { name: "Show suggestions" }))

    // A genuine critic finding is present, so the action remains meaningful.
    expect(
      screen.getByRole("button", { name: "Regenerate to address" }),
    ).toBeInTheDocument()
  })
})

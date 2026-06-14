/**
 * Harness contract for the quality badge.
 *
 * Originally T-055/T-033 asserted a numeric `score/100` badge. Issue #27
 * Phase 1 (Decision C) removes the user-facing numeric score: the badge now
 * renders a findings-derived STATUS (Ready / Needs attention / Checking /
 * Unavailable) and never a number. This contract moves with that decision —
 * a deliberate, called-out update, not a silent edit.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { QualityBadge } from "../../../frontend/src/components/workspace/QualityBadge"
import type { EvalResult } from "../../../frontend/src/types/stage"

function makeEvalResult(overrides: Partial<EvalResult> = {}): EvalResult {
  return {
    id: "eval-1",
    stage_version_id: "ver-1",
    stage_type: "spec",
    overall_score: null,
    completeness: null,
    clarity: null,
    coverage_percent: null,
    uncovered_reqs: null,
    tasks_without_ref: null,
    flagged: false,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("Quality badge renders a findings-derived status, never a number", () => {
  it("shows Ready for an eval with no actionable findings, even with a populated score", () => {
    render(<QualityBadge evalResult={makeEvalResult({ overall_score: 85 })} />)
    expect(screen.getByText("Ready")).toBeInTheDocument()
  })

  it("never renders a numeric N/100 score", () => {
    render(<QualityBadge evalResult={makeEvalResult({ overall_score: 85 })} />)
    expect(screen.queryByText(/\d+\s*\/\s*100/)).toBeNull()
    expect(screen.queryByText("85")).toBeNull()
  })

  it("shows Needs attention when the eval is flagged", () => {
    render(<QualityBadge evalResult={makeEvalResult({ flagged: true })} />)
    expect(screen.getByText("Needs attention")).toBeInTheDocument()
  })

  it("shows Checking while a stage is generating with no eval yet", () => {
    render(<QualityBadge evalResult={null} checking />)
    expect(screen.getByText("Checking")).toBeInTheDocument()
  })

  it("shows a quiet Unavailable status when validation could not complete", () => {
    render(<QualityBadge evalResult={null} error />)
    expect(screen.getByText("Unavailable")).toBeInTheDocument()
  })

  it("renders nothing when there is no eval and nothing in flight", () => {
    const { container } = render(<QualityBadge evalResult={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})

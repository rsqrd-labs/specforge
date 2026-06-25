import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { QualityBadge, deriveQualityStatus } from "./QualityBadge"
import type { EvalResult } from "../../types/stage"

function makeEval(overrides: Partial<EvalResult> = {}): EvalResult {
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

describe("QualityBadge — findings-derived status (issue #27 Phase 1)", () => {
  it("renders nothing when there is no eval and nothing in flight", () => {
    const { container } = render(<QualityBadge evalResult={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("shows Checking while the stage is generating with no eval yet", () => {
    render(<QualityBadge evalResult={null} checking />)
    expect(screen.getByText("Checking")).toBeInTheDocument()
  })

  it("shows Ready for an eval with no actionable findings — even with a null score", () => {
    render(<QualityBadge evalResult={makeEval({ overall_score: null, flagged: false })} />)
    expect(screen.getByText("Ready")).toBeInTheDocument()
  })

  it("shows Needs attention when the eval is flagged", () => {
    render(<QualityBadge evalResult={makeEval({ flagged: true })} />)
    expect(screen.getByText("Needs attention")).toBeInTheDocument()
  })

  it("shows Needs attention when harness coverage gaps exist", () => {
    render(
      <QualityBadge
        evalResult={makeEval({ stage_type: "harness", uncovered_reqs: ["FR-001"] })}
      />,
    )
    expect(screen.getByText("Needs attention")).toBeInTheDocument()
  })

  it("shows Needs attention for a genuine task gap", () => {
    render(
      <QualityBadge
        evalResult={makeEval({
          stage_type: "tasks",
          tasks_without_ref: [
            {
              task_number: 1,
              task_title: "Login",
              reason: "missing test",
              gap_type: "GENUINE_GAP",
            },
          ],
        })}
      />,
    )
    expect(screen.getByText("Needs attention")).toBeInTheDocument()
  })

  it("treats a GENERATION_FAILURE-only eval as Ready (not user-facing)", () => {
    render(
      <QualityBadge
        evalResult={makeEval({
          stage_type: "tasks",
          flagged: false,
          tasks_without_ref: [
            {
              task_number: 2,
              task_title: "CI",
              reason: "no harness refs field",
              gap_type: "GENERATION_FAILURE",
            },
          ],
        })}
      />,
    )
    expect(screen.getByText("Ready")).toBeInTheDocument()
  })

  it("treats a DEFERRED_COVERAGE-only eval as Ready (non-blocking)", () => {
    render(
      <QualityBadge
        evalResult={makeEval({
          stage_type: "tasks",
          flagged: false,
          tasks_without_ref: [
            {
              task_number: 3,
              task_title: "Perf budget",
              reason: "category deferred under budget",
              gap_type: "DEFERRED_COVERAGE",
            },
          ],
        })}
      />,
    )
    expect(screen.getByText("Ready")).toBeInTheDocument()
  })

  it("shows Unavailable (quiet, non-blocking) when validation could not complete", () => {
    render(<QualityBadge evalResult={null} error />)
    expect(screen.getByText("Unavailable")).toBeInTheDocument()
  })

  it("never renders a numeric N/100 score", () => {
    render(<QualityBadge evalResult={makeEval({ overall_score: 87, flagged: false })} />)
    expect(screen.queryByText(/\/100/)).toBeNull()
    expect(screen.queryByText("87")).toBeNull()
  })

  it("deriveQualityStatus prioritises error over everything", () => {
    expect(deriveQualityStatus(makeEval({ flagged: true }), { error: true })).toBe(
      "unavailable",
    )
  })
})

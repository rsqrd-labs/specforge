import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { CoveragePanel } from "./CoveragePanel"
import type { EvalResult, Stage } from "../../types/stage"

function makeStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "harness",
    content: "harness content",
    status: "draft",
    current_version: 1,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

function makeEval(overrides: Partial<EvalResult> = {}): EvalResult {
  return {
    id: "eval-1",
    stage_version_id: "ver-1",
    stage_type: "harness",
    overall_score: null,
    completeness: null,
    clarity: null,
    coverage_percent: null,
    uncovered_reqs: null,
    deferred_reqs: null,
    tasks_without_ref: null,
    flagged: false,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("CoveragePanel — coverage expansion (paid one-click patch)", () => {
  it("renders nothing for a clean harness (no gaps, no deferred)", () => {
    const { container } = render(
      <CoveragePanel
        stage={makeStage()}
        evalResult={makeEval()}
        onRegenerate={() => {}}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("lights the Regenerate button for a deferred-only harness", () => {
    const onRegenerate = vi.fn()
    render(
      <CoveragePanel
        stage={makeStage()}
        evalResult={makeEval({ uncovered_reqs: [], deferred_reqs: ["FR-002", "NFR-001"] })}
        onRegenerate={onRegenerate}
      />,
    )
    expect(screen.getByText("Expand Test Coverage")).toBeInTheDocument()
    expect(screen.getByText("FR-002")).toBeInTheDocument()
    expect(screen.getByText("2 optional")).toBeInTheDocument()
    // The optional expansion is paid — no "free" language.
    expect(screen.getByText(/costs 10 credits/)).toBeInTheDocument()
    // No blocking "Coverage Gaps" section when there are no genuine gaps.
    expect(screen.queryByText("Coverage Gaps")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "Regenerate HARNESS" }))
    expect(onRegenerate).toHaveBeenCalledOnce()
  })

  it("shows both sections when genuine gaps and deferred coverage coexist", () => {
    render(
      <CoveragePanel
        stage={makeStage()}
        evalResult={makeEval({
          uncovered_reqs: ["FR-009"],
          deferred_reqs: ["FR-002"],
        })}
        onRegenerate={() => {}}
      />,
    )
    expect(screen.getByText("Coverage Gaps")).toBeInTheDocument()
    expect(screen.getByText("Expand Test Coverage")).toBeInTheDocument()
    expect(screen.getByText("FR-009")).toBeInTheDocument()
    expect(screen.getByText("FR-002")).toBeInTheDocument()
  })

  it("renders only the gaps section when there is no deferred coverage", () => {
    render(
      <CoveragePanel
        stage={makeStage()}
        evalResult={makeEval({ uncovered_reqs: ["FR-009"], deferred_reqs: [] })}
        onRegenerate={() => {}}
      />,
    )
    expect(screen.getByText("Coverage Gaps")).toBeInTheDocument()
    expect(screen.queryByText("Expand Test Coverage")).toBeNull()
  })

  it("returns null on a non-harness stage", () => {
    const { container } = render(
      <CoveragePanel
        stage={makeStage({ type: "tasks" })}
        evalResult={makeEval({ deferred_reqs: ["FR-002"] })}
        onRegenerate={() => {}}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

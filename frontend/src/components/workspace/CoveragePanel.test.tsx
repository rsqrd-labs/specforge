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

  it("lights the Regenerate button for a missing-tests harness", () => {
    const onRegenerate = vi.fn()
    render(
      <CoveragePanel
        stage={makeStage()}
        evalResult={makeEval({ uncovered_reqs: [], deferred_reqs: ["FR-002", "NFR-001"] })}
        onRegenerate={onRegenerate}
      />,
    )
    expect(screen.getByText("Missing Test Coverage")).toBeInTheDocument()
    expect(screen.getByText("FR-002")).toBeInTheDocument()
    expect(screen.getByText("2 missing")).toBeInTheDocument()
    // Regenerating the missing tests is paid — no "free" language.
    expect(screen.getByText(/costs 10 credits/)).toBeInTheDocument()
    // The LLM-derived "Coverage Gaps" section is absent when uncovered_reqs is empty.
    expect(screen.queryByText("Coverage Gaps")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "Regenerate HARNESS" }))
    expect(onRegenerate).toHaveBeenCalledOnce()
  })

  it("ignores the judge's uncovered_reqs — only deterministic deferred_reqs surface", () => {
    // The judge's uncovered_reqs is truncation-poisoned (D-1) and must never
    // render a gap on its own; the panel is driven solely by deferred_reqs.
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
    expect(screen.getByText("Missing Test Coverage")).toBeInTheDocument()
    expect(screen.queryByText("Coverage Gaps")).toBeNull()
    // The judge-only requirement is not surfaced.
    expect(screen.queryByText("FR-009")).toBeNull()
    expect(screen.getByText("FR-002")).toBeInTheDocument()
  })

  it("renders nothing when only the judge's uncovered_reqs is set (no deferred)", () => {
    const { container } = render(
      <CoveragePanel
        stage={makeStage()}
        evalResult={makeEval({ uncovered_reqs: ["FR-009"], deferred_reqs: [] })}
        onRegenerate={() => {}}
      />,
    )
    expect(container).toBeEmptyDOMElement()
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

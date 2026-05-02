/**
 * Harness contract for T-055: Quality badge in StageNavigator.
 * T-033 acceptance criteria: "Quality badge (score number) shown if eval_result present on stage."
 * RED before T-055 is implemented. GREEN after StageNavigator renders inline eval scores.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { StageNavigator } from "../../../frontend/src/components/workspace/StageNavigator"
import type { Stage, EvalResult } from "../../../frontend/src/types/stage"

function makeStage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "spec",
    content: null,
    status: "draft",
    current_version: 0,
    eval_result: null,
    finalised_at: null,
    review_gate_acknowledged: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

function makeEvalResult(overrides: Partial<EvalResult> = {}): EvalResult {
  return {
    id: "eval-1",
    stage_version_id: "ver-1",
    stage_type: "spec",
    overall_score: 85,
    completeness: 80,
    clarity: 90,
    coverage_percent: null,
    uncovered_reqs: null,
    tasks_without_ref: null,
    flagged: false,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("T-055: Quality badge in StageNavigator", () => {
  it("shows the overall_score number when a stage has an eval_result", () => {
    const stages: Stage[] = [
      makeStage({
        id: "s1",
        type: "spec",
        status: "finalised",
        eval_result: makeEvalResult({ overall_score: 85 }),
      }),
      makeStage({ id: "s2", type: "plan", status: "locked" }),
      makeStage({ id: "s3", type: "harness", status: "locked" }),
      makeStage({ id: "s4", type: "tasks", status: "locked" }),
    ]
    render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={() => undefined}
      />,
    )
    expect(screen.getByText("85")).toBeInTheDocument()
  })

  it("does not render any score when eval_result is null", () => {
    const stages: Stage[] = [
      makeStage({ id: "s1", type: "spec", status: "draft", eval_result: null }),
      makeStage({ id: "s2", type: "plan", status: "locked" }),
      makeStage({ id: "s3", type: "harness", status: "locked" }),
      makeStage({ id: "s4", type: "tasks", status: "locked" }),
    ]
    render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={() => undefined}
      />,
    )
    // No numeric score should appear in the navigator for an unscored stage
    expect(screen.queryByText(/^\d+$/)).toBeNull()
  })

  it("shows scores for multiple stages that have been evaluated", () => {
    const stages: Stage[] = [
      makeStage({
        id: "s1",
        type: "spec",
        status: "finalised",
        eval_result: makeEvalResult({ overall_score: 92 }),
      }),
      makeStage({
        id: "s2",
        type: "plan",
        status: "finalised",
        eval_result: makeEvalResult({ stage_type: "plan", overall_score: 74 }),
      }),
      makeStage({ id: "s3", type: "harness", status: "locked" }),
      makeStage({ id: "s4", type: "tasks", status: "locked" }),
    ]
    render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={() => undefined}
      />,
    )
    expect(screen.getByText("92")).toBeInTheDocument()
    expect(screen.getByText("74")).toBeInTheDocument()
  })

  it("applies a green text class for scores at or above 80", () => {
    const stages: Stage[] = [
      makeStage({
        id: "s1",
        type: "spec",
        status: "finalised",
        eval_result: makeEvalResult({ overall_score: 80 }),
      }),
    ]
    const { container } = render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={() => undefined}
      />,
    )
    const scoreEl = screen.getByText("80")
    expect(scoreEl.className).toMatch(/green/i)
  })

  it("applies a red text class for scores below 60", () => {
    const stages: Stage[] = [
      makeStage({
        id: "s1",
        type: "spec",
        status: "finalised",
        eval_result: makeEvalResult({ overall_score: 55 }),
      }),
    ]
    render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={() => undefined}
      />,
    )
    const scoreEl = screen.getByText("55")
    expect(scoreEl.className).toMatch(/red/i)
  })
})

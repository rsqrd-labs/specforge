import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { CoveragePanel } from "./CoveragePanel"
import { TaskValidationPanel } from "./TaskValidationPanel"
import type { EvalResult, Stage } from "../../types/stage"

function stage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "harness",
    content: "Generated content",
    status: "draft",
    current_version: 1,
    eval_result: null,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  }
}

function evalResult(overrides: Partial<EvalResult> = {}): EvalResult {
  return {
    id: "eval-1",
    stage_version_id: "version-1",
    stage_type: "harness",
    overall_score: 80,
    completeness: 80,
    clarity: 80,
    coverage_percent: 75,
    uncovered_reqs: ["REQ-1"],
    deferred_reqs: ["REQ-1"],
    tasks_without_ref: null,
    flagged: true,
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  }
}

describe("workspace action lock panels", () => {
  it("disables coverage regeneration with a clear reason", async () => {
    const user = userEvent.setup()
    const onRegenerate = vi.fn()

    render(
      <CoveragePanel
        stage={stage()}
        evalResult={evalResult()}
        onRegenerate={onRegenerate}
        disabled
        disabledReason="Editing resumes when generation finishes."
      />,
    )

    const regenerate = screen.getByRole("button", { name: /regenerate harness/i })
    expect(regenerate).toBeDisabled()
    expect(regenerate).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )

    await user.click(regenerate)
    expect(onRegenerate).not.toHaveBeenCalled()
  })

  it("disables task gap navigation with a clear reason", async () => {
    const user = userEvent.setup()
    const onNavigateToHarness = vi.fn()

    render(
      <TaskValidationPanel
        stage={stage({ type: "tasks", id: "stage-tasks" })}
        evalResult={evalResult({
          stage_type: "tasks",
          uncovered_reqs: null,
          tasks_without_ref: [
            {
              task_number: 1,
              task_title: "Wire billing",
              reason: "Missing referenced test",
              gap_type: "GENUINE_GAP",
            },
          ],
        })}
        onNavigateToHarness={onNavigateToHarness}
        disabled
        disabledReason="Editing resumes when generation finishes."
      />,
    )

    const open = screen.getByRole("button", { name: /open harness/i })
    expect(open).toBeDisabled()
    expect(open).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )

    await user.click(open)
    expect(onNavigateToHarness).not.toHaveBeenCalled()
  })
})

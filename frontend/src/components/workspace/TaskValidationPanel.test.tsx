import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { EvalResult, Stage, TaskReferenceIssue } from "../../types/stage"
import { TaskValidationPanel } from "./TaskValidationPanel"

const stage = {
  id: "tasks-1", workspace_id: "ws", type: "tasks", content: "", status: "draft",
  current_version: 1, finalised_at: null, review_gate_acknowledged: true,
  gap_patch_used: false, created_at: "", updated_at: "",
} as Stage

const issue = (task_number: number, gap_type?: TaskReferenceIssue["gap_type"], extras: Partial<TaskReferenceIssue> = {}): TaskReferenceIssue => ({
  task_number, task_title: `Task ${task_number}`, reason: "Missing evidence", gap_type, ...extras,
})

const evaluation = (issues: TaskReferenceIssue[]): EvalResult => ({
  id: "eval", stage_version_id: "v1", stage_type: "tasks", overall_score: null,
  completeness: null, clarity: null, coverage_percent: null, uncovered_reqs: null,
  deferred_reqs: null, tasks_without_ref: issues, flagged: false, created_at: "",
})

describe("TaskValidationPanel", () => {
  it("renders only for tasks and handles loading and clean results", () => {
    const { rerender } = render(<TaskValidationPanel stage={{ ...stage, type: "spec" }} evalResult={null} />)
    expect(screen.queryByText("Coverage Gaps")).not.toBeInTheDocument()
    rerender(<TaskValidationPanel stage={stage} evalResult={null} />)
    expect(screen.getByText("Checking task traceability…")).toBeInTheDocument()
    rerender(<TaskValidationPanel stage={stage} evalResult={evaluation([])} />)
    expect(screen.queryByText("Coverage Gaps")).not.toBeInTheDocument()
  })

  it("classifies genuine, deferred, and unverified evidence with recovery actions", () => {
    const navigate = vi.fn()
    render(<TaskValidationPanel stage={stage} evalResult={evaluation([
      issue(1, undefined, { harness_file: "tests/a.py", remediation: "Add test", code_stub: "def test_a(): ..." }),
      issue(2, "GENUINE_GAP"),
      issue(3, "DEFERRED_COVERAGE", { harness_file: "tests/deferred.py" }),
      issue(4, "UNVERIFIED_COVERAGE"),
    ])} onNavigateToHarness={navigate} />)
    expect(screen.getByText("2 gaps")).toBeInTheDocument()
    expect(screen.getByText("1 deferred")).toBeInTheDocument()
    expect(screen.getByText("1 unverified")).toBeInTheDocument()
    expect(screen.getByText("def test_a(): ...")).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole("button", { name: "Open HARNESS" })[0])
    expect(navigate).toHaveBeenCalledOnce()
  })

  it("uses singular copy and explains a disabled navigation action", () => {
    render(<TaskValidationPanel stage={stage} evalResult={evaluation([
      issue(1, "GENUINE_GAP"), issue(2, "DEFERRED_COVERAGE"), issue(3, "UNVERIFIED_COVERAGE"),
    ])} onNavigateToHarness={vi.fn()} disabled disabledReason="Generation is active" />)
    expect(screen.getByText("1 gap")).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: "Open HARNESS" })[0]).toBeDisabled()
    expect(screen.getByText("Generation is active")).toBeInTheDocument()
  })

  it("does not render navigation buttons when no handler is supplied", () => {
    render(<TaskValidationPanel stage={stage} evalResult={evaluation([issue(1)])} />)
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })
})

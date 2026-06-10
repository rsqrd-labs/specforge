import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ProblemStatementPanel } from "./ProblemStatementPanel"
import type { Stage } from "../../types/stage"

function stage(overrides: Partial<Stage> = {}): Stage {
  return {
    id: "stage-spec",
    workspace_id: "ws-1",
    type: "spec",
    content: "Generated spec",
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

describe("ProblemStatementPanel", () => {
  it("renders a read-only explanation and does not edit while locked", () => {
    const onChange = vi.fn()
    render(
      <ProblemStatementPanel
        stage={stage()}
        problemStatement="A detailed enough source brief for the workspace."
        readOnly
        readOnlyReason="Editing paused. Editing resumes when generation finishes."
        onChange={onChange}
      />,
    )

    const textarea = screen.getByRole("textbox")
    expect(textarea).toHaveAttribute("readonly")
    expect(textarea).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )

    fireEvent.change(textarea, { target: { value: "Attempted edit" } })
    expect(onChange).not.toHaveBeenCalled()
  })
})

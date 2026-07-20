import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { TasksBoard } from "./TasksBoard"

const TASKS = `## Effort Summary

Two delivery tasks.

### T-001: Build the API

**Phase:** Foundation
**Priority:** MUST
**Estimate:** S
**Estimated size:** Small
**Risk:** Low
**Owner:** Backend

**Description**
Build it safely.

**Inputs**
- schema

**Outputs**
- endpoint

**Steps**
1. Implement.

**Acceptance Criteria**
1. Tests pass.

**Rollback / Recovery**
Revert the deployment.

**Dependencies**
T-002, T-999

**Spec refs:** FR-001
**Plan refs:** API section
**Harness refs:** api.test.ts

### T-002: Verify the API

**Priority:** could
**Description**
Exercise the endpoint.

### T-001: Duplicate follow-up

**Priority:** SHOULD
**Description**
Validate duplicate task identity handling.
`

describe("TasksBoard", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    window.requestAnimationFrame = (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    }
    Element.prototype.scrollIntoView = vi.fn()
  })

  it("falls back to the complete document for legacy task formats", () => {
    render(<TasksBoard content="# Legacy tasks\n\nNothing structured." />)
    expect(screen.getByRole("region", { name: "Tasks document" })).toHaveTextContent(
      "Legacy tasks",
    )
  })

  it("expands, collapses, and follows resolvable dependencies", () => {
    const { container } = render(<TasksBoard content={TASKS} />)
    expect(screen.getByText("3 tasks")).toBeInTheDocument()
    expect(container.querySelector('[id="task-T-001~1"]')).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /Build the API/ }))
    expect(screen.getByText("Foundation")).toBeInTheDocument()
    expect(screen.getByText("Traceability")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "T-999" })).toBeDisabled()

    fireEvent.click(screen.getByRole("button", { name: "T-002" }))
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    expect(container.querySelector("#task-T-002")).toHaveClass("is-highlighted")
    vi.advanceTimersByTime(2_200)

    fireEvent.click(screen.getByRole("button", { name: "Expand all" }))
    expect(screen.getByRole("button", { name: "Collapse all" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }))
    expect(screen.queryByText("Foundation")).not.toBeInTheDocument()
  })
})

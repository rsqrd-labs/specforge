import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { MemoryRouter } from "react-router"
import { StageNavigator } from "../../../frontend/src/components/workspace/StageNavigator"
import { CreditConfirmModal } from "../../../frontend/src/components/workspace/CreditConfirmModal"

describe("workspace UI contract", () => {
  it("renders locked downstream stages as disabled navigation items", () => {
    render(
      <StageNavigator
        activeStage="spec"
        stages={{
          spec: navStage("spec", "draft"),
          plan: navStage("plan", "locked"),
          harness: navStage("harness", "locked"),
          tasks: navStage("tasks", "locked"),
        }}
        onSelect={() => undefined}
      />,
    )

    expect((screen.getByRole("button", { name: /plan/i }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole("button", { name: /harness/i }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole("button", { name: /tasks/i }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("shows exact credit cost and remaining balance before LLM actions", () => {
    render(
      <MemoryRouter>
        <CreditConfirmModal
          open
          action="generate"
          creditCost={10}
          currentBalance={34}
          onCancel={() => undefined}
          onConfirm={() => undefined}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText(/10 credits/i)).toBeTruthy()
    expect(screen.getByText(/24 remaining/i)).toBeTruthy()
  })
})

function navStage(
  type: "spec" | "plan" | "harness" | "tasks",
  status: "locked" | "draft" | "in_progress" | "finalised" | "stale",
) {
  return {
    id: `${type}-id`,
    workspace_id: "workspace-id",
    type,
    content: null,
    status,
    current_version: 0,
    finalised_at: null,
    review_gate_acknowledged: false,
    created_at: "2026-04-25T00:00:00Z",
    updated_at: "2026-04-25T00:00:00Z",
  }
}

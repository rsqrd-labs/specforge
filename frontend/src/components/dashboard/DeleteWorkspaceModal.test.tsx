import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { DeleteWorkspaceModal } from "./DeleteWorkspaceModal"
import type { RetentionPolicy } from "../../types/retention"
import type { Workspace } from "../../types/workspace"

const WORKSPACE = { id: "ws-1", name: "Payments API" } as unknown as Workspace

const POLICY: RetentionPolicy = {
  policy_version: "trash-v1",
  trash_days: 30,
  legacy_archived_days: 180,
  stage_versions_keep: 20,
  stage_versions_min_age_days: 90,
  storyboards_keep: 5,
  storyboards_min_age_days: 90,
  cost_events_days: 180,
  eval_results_days: 180,
}

describe("DeleteWorkspaceModal", () => {
  it("uses trash-can copy and shows the retention window from the policy", () => {
    render(
      <DeleteWorkspaceModal
        workspace={WORKSPACE}
        error={null}
        isDeleting={false}
        policy={POLICY}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    )
    expect(
      screen.getByRole("heading", { name: /move to trash/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/30 days/)).toBeInTheDocument()
    expect(screen.getByText(/restore or export it until then/i)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /move to trash/i }),
    ).toBeInTheDocument()
  })

  it("falls back to generic window copy when the policy is unavailable", () => {
    render(
      <DeleteWorkspaceModal
        workspace={WORKSPACE}
        error={null}
        isDeleting={false}
        policy={null}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    )
    expect(screen.getByText(/after the retention window/i)).toBeInTheDocument()
  })

  it("invokes onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn()
    render(
      <DeleteWorkspaceModal
        workspace={WORKSPACE}
        error={null}
        isDeleting={false}
        policy={POLICY}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    )
    await userEvent.click(screen.getByRole("button", { name: /move to trash/i }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })
})

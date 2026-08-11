import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it, vi } from "vitest"

import type { Stage, StageStatus, StageType } from "../../types/stage"
import type { Workspace } from "../../types/workspace"
import { WorkspaceCard } from "./WorkspaceCard"

const makeStage = (type: StageType, status: StageStatus): Stage => ({
  id: type, workspace_id: "ws", type, status, content: "", current_version: 0,
  finalised_at: null, review_gate_acknowledged: false, gap_patch_used: false,
  created_at: "", updated_at: "",
})
const workspace = (stages?: Stage[]): Workspace & { stages?: Stage[] } => ({
  id: "ws", user_id: "u", name: "My workspace", problem_statement: "Problem",
  status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "", stages,
})
const renderCard = (stages?: Stage[], extras = {}) => render(
  <MemoryRouter><WorkspaceCard workspace={workspace(stages)} {...extras} /></MemoryRouter>,
)

describe("WorkspaceCard", () => {
  it.each([
    [undefined, "Ready", "Open workspace"],
    [[makeStage("spec", "draft")], "Draft", "Continue Spec"],
    [[makeStage("spec", "in_progress")], "In progress", "Resume Spec"],
    [[makeStage("spec", "stale")], "Needs refresh", "Refresh Spec"],
    [[makeStage("spec", "finalised")], "Complete", "Review Spec"],
    [[makeStage("tasks", "finalised")], "Ready to export", "Review export"],
    [[makeStage("spec", "locked")], "Locked", "Continue Spec"],
  ] as const)("describes the next action", (stages, status, action) => {
    renderCard(stages ? [...stages] : undefined)
    expect(screen.getByText(status)).toBeInTheDocument()
    expect(screen.getByText(action)).toBeInTheDocument()
  })

  it("reports completion, links to the workspace, tilts, and resets", () => {
    const { container } = renderCard([
      makeStage("spec", "finalised"), makeStage("plan", "finalised"),
      makeStage("harness", "draft"), makeStage("tasks", "locked"),
    ], { index: 2 })
    expect(screen.getByText("50%")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Open My workspace" })).toHaveAttribute("href", "/workspace/ws")
    const card = container.querySelector("article") as HTMLElement
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 200, height: 100 } as DOMRect)
    fireEvent.mouseMove(card, { clientX: 150, clientY: 25 })
    expect(card.style.transform).toContain("rotateX")
    expect(card.style.getPropertyValue("--mx")).toBe("75%")
    fireEvent.mouseLeave(card)
    expect(card.style.transform).toBe("")
  })

  it("moves a workspace to trash once and exposes pending state", () => {
    const onDelete = vi.fn()
    const { rerender } = renderCard([], { onDelete })
    fireEvent.click(screen.getByRole("button", { name: /move my workspace to trash/i }))
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ id: "ws" }))
    rerender(<MemoryRouter><WorkspaceCard workspace={workspace([])} onDelete={onDelete} isDeleting /></MemoryRouter>)
    expect(screen.getByRole("button", { name: /move my workspace to trash/i })).toBeDisabled()
  })
})

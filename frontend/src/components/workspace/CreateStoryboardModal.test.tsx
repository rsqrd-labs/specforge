import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ComponentProps } from "react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import {
  CreateStoryboardModal,
  STORYBOARD_GENERATION_COST,
  canCreateStoryboardFromStages,
  getStoryboardPrerequisites,
} from "./CreateStoryboardModal"
import type { Stage, StageType } from "../../types/stage"

const STAGE_TYPES: StageType[] = ["spec", "plan", "harness", "tasks"]

function makeStage(type: StageType, status: Stage["status"] = "finalised"): Stage {
  return {
    id: `${type}-stage`,
    workspace_id: "workspace-1",
    type,
    content: `${type} content`,
    status,
    current_version: 1,
    eval_result: null,
    finalised_at: status === "finalised" ? "2026-05-30T00:00:00Z" : null,
    review_gate_acknowledged: true,
    gap_patch_used: false,
    created_at: "2026-05-30T00:00:00Z",
    updated_at: "2026-05-30T00:00:00Z",
  }
}

function finalisedStages(): Stage[] {
  return STAGE_TYPES.map((type) => makeStage(type))
}

function renderModal(
  overrides: Partial<ComponentProps<typeof CreateStoryboardModal>> = {},
) {
  const props: ComponentProps<typeof CreateStoryboardModal> = {
    open: true,
    stages: finalisedStages(),
    currentBalance: 40,
    generateStoryboard: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  }

  return {
    ...render(
      <MemoryRouter>
        <CreateStoryboardModal {...props} />
      </MemoryRouter>,
    ),
    props,
  }
}

describe("CreateStoryboardModal", () => {
  it("shows the 25-credit price, post-action balance, and included artifacts", () => {
    renderModal()

    expect(screen.getByRole("dialog", { name: /create storyboard/i })).toBeInTheDocument()
    expect(screen.getByText(`${STORYBOARD_GENERATION_COST} credits`)).toBeInTheDocument()
    expect(screen.getByText("15 remaining")).toBeInTheDocument()

    for (const artifact of [
      "Browser keynote",
      "Architecture reveal",
      "Speaker notes",
      "Walkthrough script",
      "Technical appendix",
      "Share link",
      "PDF downloads",
      "HTML downloads",
    ]) {
      expect(screen.getByText(artifact)).toBeInTheDocument()
    }
  })

  it("blocks insufficient balance and links to billing", () => {
    renderModal({ currentBalance: 10 })

    expect(screen.getByText(/insufficient credit balance/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /open billing/i })).toHaveAttribute(
      "href",
      "/billing",
    )
    expect(
      screen.getByRole("button", { name: /create storyboard/i }),
    ).toBeDisabled()
  })

  it("shows finalised-stage prerequisite state and blocks stale prerequisites", () => {
    const stages = finalisedStages()
    stages[2] = makeStage("harness", "stale")

    renderModal({ stages, currentBalance: 40 })

    const prereq = screen.getByLabelText(/finalised-stage prerequisite state/i)
    expect(within(prereq).getByText("HARNESS")).toBeInTheDocument()
    expect(within(prereq).getByText("stale")).toBeInTheDocument()
    expect(screen.getByText(/stale or draft prerequisites/i)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /create storyboard/i }),
    ).toBeDisabled()
  })

  it("surfaces refund-aware failure language", () => {
    renderModal({ failureMessage: "Generation failed." })

    expect(screen.getByText(/generation failed/i)).toBeInTheDocument()
    expect(screen.getByText(/refund-aware/i)).toBeInTheDocument()
    expect(screen.getByText(/credits are returned/i)).toBeInTheDocument()
  })

  it("prevents duplicate generate submissions from rapid clicks", async () => {
    const user = userEvent.setup()
    const generateStoryboard = vi.fn(
      () => new Promise<void>((resolve) => window.setTimeout(resolve, 50)),
    )
    renderModal({ generateStoryboard })

    await user.dblClick(screen.getByRole("button", { name: /create storyboard/i }))

    expect(generateStoryboard).toHaveBeenCalledTimes(1)
  })
})

describe("Storyboard creation prerequisites", () => {
  it("requires all four stages to be finalised", () => {
    expect(canCreateStoryboardFromStages(finalisedStages())).toBe(true)

    const stages = finalisedStages()
    stages[1] = makeStage("plan", "draft")

    expect(canCreateStoryboardFromStages(stages)).toBe(false)
    expect(getStoryboardPrerequisites(stages)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ type: "spec", isReady: true }),
        expect.objectContaining({ type: "plan", isReady: false }),
        expect.objectContaining({ type: "harness", isReady: true }),
        expect.objectContaining({ type: "tasks", isReady: true }),
      ]),
    )
  })
})

import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { GenerateBar } from "../components/workspace/GenerateBar"
import { HumanReviewGate } from "../components/workspace/HumanReviewGate"
import { StageNavigator } from "../components/workspace/StageNavigator"
import { StalenessWarning } from "../components/workspace/StalenessWarning"
import type { Stage } from "../types/stage"

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

describe("StageNavigator", () => {
  it("renders locked stages as disabled buttons", () => {
    const stages: Stage[] = [
      makeStage({ id: "s1", type: "spec", status: "draft" }),
      makeStage({ id: "s2", type: "plan", status: "locked" }),
      makeStage({ id: "s3", type: "harness", status: "locked" }),
      makeStage({ id: "s4", type: "tasks", status: "locked" }),
    ]
    render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={vi.fn()}
      />,
    )

    expect(screen.getByRole("button", { name: /PLAN\.md/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /HARNESS/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /TASKS\.md/i })).toBeDisabled()
  })

  it("does not fire onSelectStage when a locked stage is clicked", async () => {
    const user = userEvent.setup()
    const onSelectStage = vi.fn()
    const stages: Stage[] = [
      makeStage({ id: "s1", type: "spec", status: "draft" }),
      makeStage({ id: "s2", type: "plan", status: "locked" }),
    ]
    render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={onSelectStage}
      />,
    )

    await user.click(screen.getByRole("button", { name: /PLAN\.md/i }))
    expect(onSelectStage).not.toHaveBeenCalled()
  })

  it("fires onSelectStage for an unlocked stage", async () => {
    const user = userEvent.setup()
    const onSelectStage = vi.fn()
    const stages: Stage[] = [
      makeStage({ id: "s1", type: "spec", status: "draft" }),
      makeStage({ id: "s2", type: "plan", status: "finalised" }),
    ]
    render(
      <StageNavigator
        stages={stages}
        activeStageId="s1"
        onSelectStage={onSelectStage}
      />,
    )

    await user.click(screen.getByRole("button", { name: /PLAN\.md/i }))
    expect(onSelectStage).toHaveBeenCalledWith("s2")
  })
})

describe("GenerateBar", () => {
  const noop = vi.fn()

  it("shows spinner when stage is in_progress", () => {
    const stage = makeStage({ status: "in_progress" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
      />,
    )
    expect(screen.getByText("Generating…")).toBeInTheDocument()
  })

  it("shows Generate button when stage is draft with no content", () => {
    const stage = makeStage({ status: "draft", content: null })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
      />,
    )
    expect(screen.getByRole("button", { name: /generate/i })).toBeInTheDocument()
  })

  it("returns null when stage is locked", () => {
    const stage = makeStage({ status: "locked" })
    const { container } = render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
      />,
    )
    expect(container.firstChild).toBeNull()
  })
})

describe("StalenessWarning", () => {
  it("renders when stage is stale", () => {
    const stage = makeStage({ type: "plan", status: "stale" })
    render(
      <StalenessWarning
        stage={stage}
        upstreamStageType="SPEC.md"
        onRegenerate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /keep as-is/i })).toBeInTheDocument()
    expect(screen.getByText(/SPEC\.md/)).toBeInTheDocument()
  })

  it("renders nothing when stage is not stale", () => {
    const stage = makeStage({ status: "draft" })
    const { container } = render(
      <StalenessWarning
        stage={stage}
        upstreamStageType="SPEC.md"
        onRegenerate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it("calls onRegenerate when Regenerate button clicked", async () => {
    const user = userEvent.setup()
    const onRegenerate = vi.fn()
    const stage = makeStage({ status: "stale" })
    render(
      <StalenessWarning
        stage={stage}
        upstreamStageType="SPEC.md"
        onRegenerate={onRegenerate}
        onDismiss={vi.fn()}
      />,
    )
    await user.click(screen.getByRole("button", { name: /regenerate/i }))
    expect(onRegenerate).toHaveBeenCalledOnce()
  })
})

describe("HumanReviewGate", () => {
  it("renders source and target stage names", () => {
    render(
      <HumanReviewGate
        fromStageType="SPEC.md"
        toStageType="PLAN.md"
        onProceed={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByText(/PLAN\.md/)).toBeInTheDocument()
    expect(screen.getByText(/SPEC\.md/)).toBeInTheDocument()
  })

  it("calls onProceed when Proceed is clicked", async () => {
    const user = userEvent.setup()
    const onProceed = vi.fn()
    render(
      <HumanReviewGate
        fromStageType="SPEC.md"
        toStageType="PLAN.md"
        onProceed={onProceed}
        onClose={vi.fn()}
      />,
    )
    await user.click(screen.getByRole("button", { name: /proceed/i }))
    expect(onProceed).toHaveBeenCalledOnce()
  })

  it("calls onClose when Cancel is clicked", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <HumanReviewGate
        fromStageType="SPEC.md"
        toStageType="PLAN.md"
        onProceed={vi.fn()}
        onClose={onClose}
      />,
    )
    await user.click(screen.getByRole("button", { name: /cancel/i }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

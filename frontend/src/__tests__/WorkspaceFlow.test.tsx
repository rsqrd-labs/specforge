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
    gap_patch_used: false,
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

    expect(screen.getByRole("button", { name: /plan/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /harness/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /tasks/i })).toBeDisabled()
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

    await user.click(screen.getByRole("button", { name: /plan/i }))
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

    await user.click(screen.getByRole("button", { name: /plan/i }))
    expect(onSelectStage).toHaveBeenCalledWith("s2")
  })
})

describe("GenerateBar", () => {
  const noop = vi.fn()

  it("shows a compact busy state when stage is in_progress", () => {
    const stage = makeStage({ status: "in_progress" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
        onUnlock={noop}
      />,
    )
    expect(screen.getByRole("status")).toHaveTextContent("Generating stage...")
  })

  it("labels refinement busy work distinctly", () => {
    const stage = makeStage({ status: "draft", content: "Existing spec" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
        onUnlock={noop}
        isBusy
        busyOperation="focused-patch"
      />,
    )
    expect(screen.getByRole("status")).toHaveTextContent("Preparing refinement...")
    expect(
      screen.queryByRole("button", { name: /refine spec/i }),
    ).not.toBeInTheDocument()
  })

  it("uses explicit workspace-lock busy copy when another stage is generating", () => {
    const stage = makeStage({ type: "spec", status: "draft", content: "Existing spec" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
        onUnlock={noop}
        isBusy
        busyLabel="Generating PLAN. Editing paused."
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent(
      "Generating PLAN. Editing paused.",
    )
  })

  it.each([
    ["spec", "SPEC"],
    ["plan", "PLAN"],
    ["harness", "HARNESS"],
    ["tasks", "TASKS"],
  ] as const)(
    "shows a concise Generate button with %s context",
    (type, label) => {
      const stage = makeStage({ type, status: "draft", content: null })
      render(
        <GenerateBar
          stage={stage}
          onGenerate={noop}
          onRegenerate={noop}
          onRefine={noop}
          onFinalise={noop}
          onUnlock={noop}
        />,
      )

      const button = screen.getByRole("button", { name: `Generate ${label}` })
      expect(button).toHaveTextContent(/^Generate$/)
    },
  )

  it("labels available stage actions with concise visible copy", () => {
    const stage = makeStage({ status: "draft", content: "Existing spec" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
        onUnlock={noop}
      />,
    )
    const regenerate = screen.getByRole("button", { name: /regenerate spec/i })
    expect(regenerate).toHaveTextContent(/^Regenerate$/)
    expect(regenerate).toHaveClass("gen-btn-deliberate")
    expect(screen.getByRole("button", { name: /refine spec/i })).toHaveTextContent(/^Refine$/)
    expect(screen.getByRole("button", { name: /finalise spec/i })).toHaveTextContent(/^Finalise$/)
  })

  it("does not render obsolete internal action labels", () => {
    const commonProps = {
      onGenerate: noop,
      onRegenerate: noop,
      onRefine: noop,
      onFinalise: noop,
      onUnlock: noop,
    }
    render(
      <>
        {(["spec", "plan", "harness", "tasks"] as const).map((type) => (
          <GenerateBar
            key={type}
            stage={makeStage({ id: `stage-${type}`, type, status: "draft", content: null })}
            {...commonProps}
          />
        ))}
        <GenerateBar
          stage={makeStage({ id: "stage-with-content", status: "draft", content: "Existing spec" })}
          {...commonProps}
        />
      </>,
    )

    for (const oldLabel of [
      "Generate " + "requirements pass",
      "Generate " + "architecture pass",
      "Generate " + "validation harness",
      "Generate " + "implementation plan",
      "Full stage " + "regenerate",
      "Focused " + "patch",
      "Final quality " + "pass",
    ]) {
      expect(screen.queryByText(oldLabel)).not.toBeInTheDocument()
    }
  })

  it("disables finalise while quality gate is blocked", () => {
    const stage = makeStage({ status: "draft", content: "Blocked spec" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
        onUnlock={noop}
        qualityGateBlocked
      />,
    )
    expect(screen.getByRole("button", { name: /finalise spec/i })).toBeDisabled()
  })

  it("shows a visible, accessible reason when finalise is gate-blocked", () => {
    // A disabled button is unreliably announced by assistive tech, so the
    // reason must be a genuinely visible note (issue #28, Phase 2), with
    // aria-describedby as reinforcement.
    const stage = makeStage({ status: "draft", content: "Blocked spec" })
    const message =
      "This version stopped before it was complete and can't be finalised."
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
        onUnlock={noop}
        qualityGateBlocked
        qualityGateBlockedMessage={message}
      />,
    )

    const note = screen.getByRole("note")
    expect(note).toHaveTextContent(message)
    expect(screen.getByRole("button", { name: /finalise spec/i })).toHaveAccessibleDescription(
      message,
    )
  })

  it("omits the gate reason note when finalise is not blocked", () => {
    const stage = makeStage({ status: "draft", content: "Clean spec" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={noop}
        onUnlock={noop}
      />,
    )
    expect(screen.queryByRole("note")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /finalise spec/i })).toBeEnabled()
  })

  it("offers an enabled Finalise action for a stale stage and fires onFinalise", async () => {
    // A stale stage still surfaces "Finalise" (the page routes that click to the
    // credit-free acknowledge path, not finaliseStage which rejects non-drafts).
    const user = userEvent.setup()
    const onFinalise = vi.fn()
    const stage = makeStage({ status: "stale", content: "Existing tasks" })
    render(
      <GenerateBar
        stage={stage}
        onGenerate={noop}
        onRegenerate={noop}
        onRefine={noop}
        onFinalise={onFinalise}
        onUnlock={noop}
      />,
    )
    const finaliseBtn = screen.getByRole("button", { name: /finalise spec/i })
    expect(finaliseBtn).toBeEnabled()
    await user.click(finaliseBtn)
    expect(onFinalise).toHaveBeenCalledOnce()
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
        onUnlock={noop}
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
    expect(screen.getByRole("button", { name: /^keep$/i })).toBeInTheDocument()
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

  it("calls onDismiss (Keep — accept content as-is) when Keep clicked", async () => {
    const user = userEvent.setup()
    const onDismiss = vi.fn()
    const stage = makeStage({ status: "stale" })
    render(
      <StalenessWarning
        stage={stage}
        upstreamStageType="SPEC.md"
        onRegenerate={vi.fn()}
        onDismiss={onDismiss}
      />,
    )
    await user.click(screen.getByRole("button", { name: /^keep$/i }))
    expect(onDismiss).toHaveBeenCalledOnce()
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

  it("calls onProceed when Generate is clicked", async () => {
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
    await user.click(screen.getByRole("button", { name: /^generate$/i }))
    expect(onProceed).toHaveBeenCalledOnce()
  })

  it("calls onClose when Back is clicked", async () => {
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
    await user.click(screen.getByRole("button", { name: /^back$/i }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

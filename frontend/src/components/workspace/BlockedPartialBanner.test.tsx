import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { QualityGateInfo, Stage } from "../../types/stage"
import {
  BlockedPartialBadge,
  BlockedPartialNotice,
} from "./BlockedPartialBanner"

function makeStage(quality_gate?: QualityGateInfo | null): Stage {
  return {
    id: "stage-1",
    workspace_id: "ws-1",
    type: "spec",
    content: "partial document",
    status: "draft",
    current_version: 2,
    eval_result: null,
    finalised_at: null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    quality_gate: quality_gate ?? null,
    created_at: "2026-06-14T00:00:00Z",
    updated_at: "2026-06-14T00:00:00Z",
  }
}

function blockedGate(kind: string, recoveryMessage?: string): QualityGateInfo {
  return {
    stage: "spec",
    kind,
    status: "blocked",
    recovery: recoveryMessage
      ? {
          action: "regenerate",
          overridable: kind === "missing_sections" || kind === "critic_findings",
          credit_required: 10,
          refunded_prior_attempt: kind === "incomplete_output",
          message: recoveryMessage,
        }
      : null,
  }
}

describe("BlockedPartialBadge", () => {
  it("renders nothing when the stage is not blocked", () => {
    const { container } = render(<BlockedPartialBadge stage={makeStage(null)} />)
    expect(container.firstChild).toBeNull()
  })

  it("renders nothing for a null/undefined stage", () => {
    const { container } = render(<BlockedPartialBadge stage={null} />)
    expect(container.firstChild).toBeNull()
    const { container: c2 } = render(<BlockedPartialBadge stage={undefined} />)
    expect(c2.firstChild).toBeNull()
  })

  it("renders nothing for a cleared/overridden gate, not a blocked one", () => {
    const stage = makeStage({ stage: "spec", kind: null, status: "overridden" })
    const { container } = render(<BlockedPartialBadge stage={stage} />)
    expect(container.firstChild).toBeNull()
  })

  // The Phase 2 guarantee: the badge derives ENTIRELY from the stage object —
  // it has no `qualityGateMap` prop, so there is nothing to lose on dismiss or
  // refresh. Rendering from a blocked stage prop alone IS that proof.
  it("labels an incomplete_output block a 'Blocked partial draft'", () => {
    render(
      <BlockedPartialBadge
        stage={makeStage(blockedGate("incomplete_output", "Regenerate to finish it."))}
      />,
    )
    const badge = screen.getByText("Blocked partial draft")
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute("title", "Regenerate to finish it.")
  })

  it.each(["technology_safety", "critic_findings", "missing_sections"])(
    "labels a complete-but-flagged %s block a plain 'Blocked draft'",
    (kind) => {
      render(<BlockedPartialBadge stage={makeStage(blockedGate(kind))} />)
      expect(screen.getByText("Blocked draft")).toBeInTheDocument()
      expect(screen.queryByText("Blocked partial draft")).not.toBeInTheDocument()
    },
  )
})

describe("BlockedPartialNotice", () => {
  it("keeps the blocked label and reason visible after the panel is collapsed", () => {
    render(
      <BlockedPartialNotice
        label="Blocked partial draft"
        message="This version stopped before it was complete and can't be finalised."
      />,
    )
    expect(screen.getByText("Blocked partial draft")).toBeInTheDocument()
    expect(
      screen.getByText(/stopped before it was complete/i),
    ).toBeInTheDocument()
  })

  it("offers 'Show details' to re-expand the panel when a handler is provided", async () => {
    const user = userEvent.setup()
    const onShowDetails = vi.fn()
    render(
      <BlockedPartialNotice
        label="Blocked draft"
        message="Regenerate or override the quality gate before finalising"
        onShowDetails={onShowDetails}
      />,
    )
    await user.click(screen.getByRole("button", { name: "Show details" }))
    expect(onShowDetails).toHaveBeenCalledOnce()
  })

  it("omits 'Show details' when there is nothing to re-expand", () => {
    render(
      <BlockedPartialNotice label="Blocked draft" message="Regenerate first." />,
    )
    expect(
      screen.queryByRole("button", { name: "Show details" }),
    ).not.toBeInTheDocument()
  })
})

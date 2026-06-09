import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { QualityGateInfo } from "../../types/stage"
import "../../index.css"
import { StreamingOverlay } from "./StreamingOverlay"

const criticGate: QualityGateInfo = {
  stage: "plan",
  kind: "critic_findings",
  findings: [
    {
      kind: "MissingCoverage",
      detail: "ADR-001 is not referenced.",
      reference: "ADR-001",
    },
  ],
}

const incompleteGate: QualityGateInfo = {
  stage: "tasks",
  kind: "incomplete_output",
  override_allowed: false,
  repair_attempted: true,
  reasons: [
    {
      code: "provider_stopped_by_limit",
      detail: "The provider stopped because the output token limit was reached.",
      reference: "max_tokens",
    },
  ],
}

const technologySafetyGate: QualityGateInfo = {
  stage: "plan",
  kind: "technology_safety",
  override_allowed: false,
  repair_attempted: true,
  policy_version: "tech-safety-v1",
  reasons: [
    {
      code: "runtime_eol",
      severity: "critical",
      technology: "Node.js",
      version: "18",
      source: "local_policy",
      detail: "Node.js 18 is EOL. Choose Node.js 22 LTS or newer.",
      reference: "Node.js",
      remediation: "Choose Node.js 22 LTS or newer.",
    },
  ],
}

describe("StreamingOverlay quality gate", () => {
  it("wires regenerate, override, and dismiss actions", async () => {
    const user = userEvent.setup()
    const onRegenerate = vi.fn()
    const onOverride = vi.fn()
    const onDismiss = vi.fn()

    render(
      <StreamingOverlay
        isVisible={false}
        gate={criticGate}
        onRegenerate={onRegenerate}
        onOverride={onOverride}
        onDismiss={onDismiss}
      />,
    )

    await user.click(screen.getByRole("button", { name: "Regenerate" }))
    await user.click(screen.getByRole("button", { name: "Override and continue" }))
    await user.click(screen.getByRole("button", { name: "Dismiss" }))

    expect(onRegenerate).toHaveBeenCalledOnce()
    expect(onOverride).toHaveBeenCalledOnce()
    expect(onDismiss).toHaveBeenCalledOnce()
  })

  it("keeps the gate overlay clickable in CSS", () => {
    render(<StreamingOverlay isVisible={false} gate={criticGate} />)

    expect(
      getComputedStyle(screen.getByRole("alertdialog", { name: /quality gate/i }))
      .pointerEvents,
    ).toBe("auto")
  })

  it("hides override for incomplete output gates", () => {
    render(
      <StreamingOverlay
        isVisible={false}
        gate={incompleteGate}
        onRegenerate={vi.fn()}
        onOverride={vi.fn()}
      />,
    )

    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Override and continue" }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/stopped before completion/i)).toBeInTheDocument()
  })

  it("hides override and renders remediation for technology safety gates", () => {
    render(
      <StreamingOverlay
        isVisible={false}
        gate={technologySafetyGate}
        onRegenerate={vi.fn()}
        onOverride={vi.fn()}
      />,
    )

    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Override and continue" }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/unsafe or unsupported technology/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Node\.js 22 LTS/i).length).toBeGreaterThan(0)
  })
})

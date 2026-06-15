import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import type { QualityGateInfo } from "../../types/stage"
import "../../index.css"
import { useGenerationEstimatesStore } from "../../store/generationEstimatesStore"
import {
  phaseLivenessCopy,
  StreamingOverlay,
  type GenerationActivityInfo,
  type GenerationActivityOperation,
} from "./StreamingOverlay"

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
  recovery: {
    action: "regenerate",
    overridable: false,
    credit_required: 10,
    refunded_prior_attempt: true,
    message:
      "This version stopped before it was complete and can't be finalised. " +
      "Regenerate to produce a full version. Your previous attempt was refunded.",
  },
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
  recovery: {
    action: "regenerate",
    overridable: false,
    credit_required: 10,
    refunded_prior_attempt: true,
    message:
      "This version proposes unsafe technology choices and can't be finalised. " +
      "Regenerate to continue. Your previous attempt was refunded.",
  },
}

function activity(
  operation: GenerationActivityOperation,
  stageType: GenerationActivityInfo["stageType"] = "spec",
): GenerationActivityInfo {
  return {
    stageId: `stage-${stageType}`,
    stageType,
    operation,
    actionLabel: operation,
    startedAt: 0,
    streamed: operation !== "focused-patch",
  }
}

describe("StreamingOverlay generation activity", () => {
  it.each([
    ["generate", "spec", "Structuring requirements"],
    ["generate", "plan", "Designing architecture"],
    ["generate", "harness", "Building validation harness"],
    ["generate", "tasks", "Drafting implementation plan"],
    ["focused-patch", "plan", "Preparing refinement"],
    ["quality-gate-regenerate", "tasks", "Regenerating with gate feedback"],
    ["regenerate-gaps", "tasks", "Regenerating coverage gaps"],
  ] as const)(
    "renders accessible status copy for %s on %s",
    (operation, stageType, expectedCopy) => {
      render(
        <StreamingOverlay
          isVisible
          activity={activity(operation, stageType)}
        />,
      )

      const status = screen.getByRole("status")
      expect(status).toHaveAttribute("aria-live", "polite")
      expect(status).toHaveAttribute("aria-busy", "true")
      expect(status).toHaveTextContent(expectedCopy)
    },
  )

  it("keeps the generation overlay inside the document interaction layer", () => {
    render(<StreamingOverlay isVisible activity={activity("generate", "plan")} />)

    expect(getComputedStyle(screen.getByRole("status")).pointerEvents).toBe("auto")
  })

  it("shows an elapsed-time liveness line so a long generation never looks frozen", () => {
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity("generate", "spec"), startedAt: Date.now() }}
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent(/elapsed/)
  })

  it("collapses to a slim pill while live draft tokens render in the editor", () => {
    render(
      <StreamingOverlay
        isVisible
        compact
        activity={{ ...activity("generate", "spec"), startedAt: Date.now() }}
      />,
    )

    const pill = screen.getByRole("status")
    expect(pill).toHaveClass("generation-streaming-pill")
    expect(pill).toHaveTextContent("Structuring requirements")
    // The full-card loading overlay must not cover the document.
    expect(document.querySelector(".generation-loading-overlay")).toBeNull()
  })

  it("confirms backend liveness when a progress heartbeat has arrived", () => {
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity("generate", "spec"), startedAt: Date.now() }}
        progress={{ stage: "spec", state: "generating", elapsed_seconds: 42 }}
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent(
      "the model is working; this can take several minutes.",
    )
  })

  it("keeps the generic liveness copy (ignores progress.phase) while the flag is off", () => {
    // Phase 2c phase-specific copy is gated on branded_loaders (off in this
    // file). Even with a phase on the heartbeat, the flag-off path must stay
    // byte-identical to the pre-2c generic copy.
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity("generate", "spec"), startedAt: Date.now() }}
        progress={{
          stage: "spec",
          state: "generating",
          elapsed_seconds: 42,
          phase: "critic",
        }}
      />,
    )

    const status = screen.getByRole("status")
    expect(status).toHaveTextContent(
      "the model is working; this can take several minutes.",
    )
    expect(status).not.toHaveTextContent(/reviewer model/i)
  })
})

describe("phaseLivenessCopy (Phase 2c)", () => {
  it.each([
    ["streaming", /drafting/i],
    ["quality_gate", /quality gates/i],
    ["critic", /reviewer model/i],
    ["persisting", /finalising and saving/i],
  ] as const)("maps the %s phase to honest copy", (phase, pattern) => {
    expect(phaseLivenessCopy(phase)).toMatch(pattern)
  })

  it("returns null for an unknown phase so the caller uses the generic copy", () => {
    expect(phaseLivenessCopy("future_phase")).toBeNull()
    expect(phaseLivenessCopy("")).toBeNull()
  })
})

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
    await user.click(screen.getByRole("button", { name: "Hide details" }))

    expect(onRegenerate).toHaveBeenCalledOnce()
    expect(onOverride).toHaveBeenCalledOnce()
    expect(onDismiss).toHaveBeenCalledOnce()
  })

  it("disables quality-gate actions with a lock reason", async () => {
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
        actionsDisabled
        disabledReason="Editing resumes when generation finishes."
      />,
    )

    const regenerate = screen.getByRole("button", { name: "Regenerate" })
    expect(regenerate).toBeDisabled()
    expect(regenerate).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )

    await user.click(regenerate)
    await user.click(screen.getByRole("button", { name: "Override and continue" }))
    await user.click(screen.getByRole("button", { name: "Hide details" }))

    expect(onRegenerate).not.toHaveBeenCalled()
    expect(onOverride).not.toHaveBeenCalled()
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it("keeps the gate overlay clickable in CSS", () => {
    render(<StreamingOverlay isVisible={false} gate={criticGate} />)

    expect(
      getComputedStyle(screen.getByRole("alertdialog", { name: /quality gate/i }))
      .pointerEvents,
    ).toBe("auto")
  })

  it("offers a 'Retry generation' CTA + refund sub-copy for incomplete output gates", () => {
    // Phase 3 (issue #28): for a non-overridable block the retry IS the recovery,
    // so the primary action is the explicit, non-punitive "Retry generation" and
    // the refund is stated plainly so the gate never feels like a paywall.
    render(
      <StreamingOverlay
        isVisible={false}
        gate={incompleteGate}
        onRegenerate={vi.fn()}
        onOverride={vi.fn()}
      />,
    )

    expect(
      screen.getByRole("button", { name: "Retry generation" }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Regenerate" }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Override and continue" }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/stopped before completion/i)).toBeInTheDocument()
    expect(screen.getByRole("note")).toHaveTextContent(
      "Your previous attempt was refunded.",
    )
  })

  it("renames the CTA and renders remediation for technology safety gates", () => {
    render(
      <StreamingOverlay
        isVisible={false}
        gate={technologySafetyGate}
        onRegenerate={vi.fn()}
        onOverride={vi.fn()}
      />,
    )

    expect(
      screen.getByRole("button", { name: "Retry generation" }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Override and continue" }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/unsafe or unsupported technology/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Node\.js 22 LTS/i).length).toBeGreaterThan(0)
    expect(screen.getByRole("note")).toHaveTextContent(
      "Your previous attempt was refunded.",
    )
  })

  it("omits the refund sub-copy when no refund actually happened", () => {
    // The note is driven solely by the backend refund truth: a finalise-time
    // re-check sets refunded_prior_attempt false and we must not imply a refund.
    render(
      <StreamingOverlay
        isVisible={false}
        gate={{
          ...incompleteGate,
          recovery: {
            ...incompleteGate.recovery!,
            refunded_prior_attempt: false,
          },
        }}
        onRegenerate={vi.fn()}
      />,
    )

    expect(
      screen.getByRole("button", { name: "Retry generation" }),
    ).toBeInTheDocument()
    expect(screen.queryByRole("note")).not.toBeInTheDocument()
  })

  it("keeps 'Regenerate' (not 'Retry generation') and no refund note for overridable kinds", () => {
    // critic_findings is overridable and carries no refund contract in this
    // fixture — the recovery CTA rename is scoped to non-overridable blocks only.
    render(
      <StreamingOverlay
        isVisible={false}
        gate={criticGate}
        onRegenerate={vi.fn()}
        onOverride={vi.fn()}
      />,
    )

    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: "Retry generation" }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Override and continue" }),
    ).toBeInTheDocument()
    expect(screen.queryByRole("note")).not.toBeInTheDocument()
  })

  it("does not fetch live estimates while the branded-loaders flag is off", () => {
    // Flag is off in this file (the branded path is covered separately). Even
    // with a provider on the activity, the loading screen must make zero new
    // network calls — the live fetch is gated on the same flag that renders the
    // ETA bar, preserving the flag-off path byte-for-byte (Phase 2b).
    const ensureLoaded = vi.fn(async () => {})
    useGenerationEstimatesStore.setState({ ensureLoaded })

    render(
      <StreamingOverlay
        isVisible
        activity={{
          stageId: "stage-spec",
          stageType: "spec",
          operation: "generate",
          actionLabel: "generate",
          startedAt: Date.now(),
          streamed: true,
          provider: "anthropic",
        }}
      />,
    )

    expect(ensureLoaded).not.toHaveBeenCalled()
  })
})

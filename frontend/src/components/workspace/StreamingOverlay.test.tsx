import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

// `branded_loaders` now ships ON by default, so this file pins it OFF to keep
// exercising the legacy per-surface loader / default-off path. The flag-ON
// (animated squirrel) behavior is covered in StreamingOverlay.branded.test.tsx.
vi.mock("../../config/featureFlags", () => ({
  featureFlags: { brandedLoaders: false },
}))

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
  // Issue #34: overridable now; incomplete_output still refunds.
  override_allowed: true,
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
    overridable: true,
    credit_required: 10,
    refunded_prior_attempt: true,
    message:
      "This draft looks cut off before it finished. Regenerate for a complete " +
      "version, or finalise this one as-is if it already covers what you need. " +
      "Your credit for this attempt was refunded.",
  },
}

const technologySafetyGate: QualityGateInfo = {
  stage: "plan",
  kind: "technology_safety",
  // Issue #34: overridable now; technology_safety no longer refunds.
  override_allowed: true,
  repair_attempted: true,
  policy_version: "tech-safety-v1",
  reasons: [
    {
      code: "technology_eol",
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
    overridable: true,
    credit_required: 10,
    refunded_prior_attempt: false,
    message:
      "This draft suggests a technology that's out of date or unsupported. " +
      "Regenerate to get an up-to-date version, or finalise this one as-is if " +
      "the choice is intentional.",
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

  it("keeps cancellation available in compact streaming mode", async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    render(
      <StreamingOverlay
        isVisible
        compact
        activity={{ ...activity("generate", "plan"), startedAt: Date.now() }}
        onCancel={onCancel}
      />,
    )

    await user.click(screen.getByRole("button", { name: "Cancel" }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it("shows the absolute limit and server-owned stopping state", () => {
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity("generate", "harness"), startedAt: Date.now() }}
        progress={{
          generation_id: "run-1",
          stage: "harness",
          state: "generating",
          phase: "stopping",
          elapsed_seconds: 84,
          deadline: new Date(Date.now() + 216_000).toISOString(),
        }}
        onCancel={vi.fn()}
        isStopping
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent(/stopping server-side work/i)
    expect(document.querySelector(".generation-deadline")).toHaveTextContent(
      /processing limit/i,
    )
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled()
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

  it("shows honest, monotonic part progress while the parallel path drafts (issue #39)", () => {
    // The parallel chunked path's silent (non-lead) chunks show no text; the
    // part counter is the liveness signal that the whole set is advancing, so it
    // renders independent of the branded-loaders flag.
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity("generate", "spec"), startedAt: Date.now() }}
        progress={{
          stage: "spec",
          state: "generating",
          elapsed_seconds: 42,
          phase: "drafting",
          completed_parts: 2,
          total_parts: 3,
        }}
      />,
    )

    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 parts drafted")
  })

  it("hides the part counter once generation leaves the drafting phases", () => {
    // After every part is drafted the pipeline moves to the gate/critic phases,
    // where a stale "3 of 3 parts" would mislead — so the counter disappears.
    render(
      <StreamingOverlay
        isVisible
        activity={{ ...activity("generate", "spec"), startedAt: Date.now() }}
        progress={{
          stage: "spec",
          state: "generating",
          elapsed_seconds: 42,
          phase: "critic",
          completed_parts: 3,
          total_parts: 3,
        }}
      />,
    )

    expect(screen.queryByText(/parts drafted/)).toBeNull()
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
    ["preparing", /preparing prompts/i],
    ["drafting", /model is drafting/i],
    ["assembling", /canonical order/i],
    ["validating", /quality gates/i],
    ["saving", /finalising and saving/i],
    ["stopping", /saving safe partial output/i],
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

  it("offers a free resume as the primary action on a resumable gate", () => {
    // The partial-loss defect: 3 of 4 chunks succeeded, the 4th timed out, and
    // the old behaviour refunded the credit and threw the 3 away. Now the
    // banked sections are kept and only the gap is offered — for free.
    const onResume = vi.fn()
    const onRegenerate = vi.fn()
    render(
      <StreamingOverlay
        isVisible={false}
        gate={{
          ...incompleteGate,
          resumable: true,
          // The backend sends rendered labels, never raw chunk keys — every
          // stage describes its progress in the same voice.
          completed_sections: [
            "Product scope and requirements",
            "System expectations and constraints",
          ],
          missing_sections: ["Validation and risks"],
          recovery: {
            action: "resume",
            overridable: true,
            credit_required: 0,
            refunded_prior_attempt: false,
            message:
              "2 of 3 sections were generated and saved. Finish the remaining " +
              "1 section at no extra credit cost, or finalise this draft as-is.",
          },
        }}
        onRegenerate={onRegenerate}
        onResume={onResume}
        onOverride={vi.fn()}
      />,
    )

    // Headline reframes a partial success as progress, not a failure.
    expect(screen.getByText("2 of 3 sections generated")).toBeInTheDocument()
    expect(screen.getByText(/no extra credit cost/i)).toBeInTheDocument()
    // The outstanding section is named, so the user knows what they are buying.
    expect(screen.getByText(/Validation and risks/)).toBeInTheDocument()

    const resume = screen.getByRole("button", { name: /finish remaining/i })
    resume.click()
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(onRegenerate).not.toHaveBeenCalled()

    // Regenerate is demoted to "Start over" — it discards work already paid for.
    expect(screen.getByRole("button", { name: "Start over" })).toBeInTheDocument()
    // Nothing was refunded, so the refund note must not appear.
    expect(screen.queryByText(/was refunded/i)).not.toBeInTheDocument()
  })

  it("keeps the plain incomplete gate unchanged when it is not resumable", () => {
    const onResume = vi.fn()
    render(
      <StreamingOverlay
        isVisible={false}
        gate={incompleteGate}
        onRegenerate={vi.fn()}
        onResume={onResume}
        onOverride={vi.fn()}
      />,
    )

    // A gate with no banked sections must never advertise a free resume.
    expect(
      screen.queryByRole("button", { name: /finish remaining/i }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument()
    expect(onResume).not.toHaveBeenCalled()
  })

  it("offers Regenerate + Override + refund sub-copy for incomplete output gates", () => {
    // Issue #34: incomplete_output is overridable now — the user can regenerate
    // OR finalise as-is. incomplete_output still refunds, so the note shows.
    render(
      <StreamingOverlay
        isVisible={false}
        gate={incompleteGate}
        onRegenerate={vi.fn()}
        onOverride={vi.fn()}
      />,
    )

    expect(
      screen.getByRole("button", { name: "Regenerate" }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Override and continue" }),
    ).toBeInTheDocument()
    expect(screen.getByText(/stopped before completion/i)).toBeInTheDocument()
    expect(screen.getByRole("note")).toHaveTextContent(
      "Your previous attempt was refunded.",
    )
  })

  it("offers Regenerate + Override + no refund note for technology safety gates", () => {
    // Issue #34: technology_safety is overridable now and no longer refunds.
    render(
      <StreamingOverlay
        isVisible={false}
        gate={technologySafetyGate}
        onRegenerate={vi.fn()}
        onOverride={vi.fn()}
      />,
    )

    expect(
      screen.getByRole("button", { name: "Regenerate" }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Override and continue" }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/outdated or unsupported technology/i),
    ).toBeInTheDocument()
    expect(screen.getAllByText(/Node\.js 22 LTS/i).length).toBeGreaterThan(0)
    expect(screen.queryByRole("note")).not.toBeInTheDocument()
    // The finding code and severity render as plain language, never raw jargon.
    expect(screen.getByText("End-of-life technology")).toBeInTheDocument()
    expect(screen.queryByText("technology_eol")).not.toBeInTheDocument()
    expect(screen.getByText(/· Critical/)).toBeInTheDocument()
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
      screen.getByRole("button", { name: "Regenerate" }),
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
        }}
      />,
    )

    expect(ensureLoaded).not.toHaveBeenCalled()
  })
})

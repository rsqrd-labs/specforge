import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { DemoDayHandoffPanel } from "./DemoDayHandoffPanel"
import type { Stage, StageType } from "../../types/stage"
import type { ConstructionVerdict } from "../../types/workspace"

const STAGE_TYPES: StageType[] = ["spec", "plan", "harness", "tasks"]

function stagesAt(version: number): Pick<Stage, "type" | "current_version">[] {
  return STAGE_TYPES.map((type) => ({ type, current_version: version }))
}

function verdict(overrides: Partial<ConstructionVerdict> = {}): ConstructionVerdict {
  return {
    verified: true,
    checks: {
      C1: { name: "dag_acyclic", passed: true, gaps: [] },
      C2: { name: "task_to_test", passed: true, gaps: [] },
      C3: { name: "ac_to_test", passed: true, gaps: [] },
      C4: { name: "e2e_reachable", passed: true, gaps: [] },
      C5: { name: "time_budget", passed: true, gaps: [] },
    },
    estimated_minutes: 240,
    time_budget_minutes: 300,
    stage_versions: { spec: 1, plan: 1, harness: 1, tasks: 1 },
    ...overrides,
  }
}

describe("DemoDayHandoffPanel", () => {
  it("shows the verified guarantee copy and the CLAUDE.md bundle by default", () => {
    render(
      <DemoDayHandoffPanel
        verdict={verdict()}
        stages={stagesAt(1)}
        targetAgent="claude_code"
        onDownloadBundle={vi.fn()}
      />,
    )
    expect(screen.getByText("Verified ✓")).toBeInTheDocument()
    expect(
      screen.getByText(/the prototype does what your approved spec says/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Download handoff bundle for CLAUDE\.md/ }),
    ).toBeInTheDocument()
    // Advisory build-time line, framed as a target — never a guarantee.
    expect(screen.getByText(/Estimated build time ~4h/)).toBeInTheDocument()
    expect(screen.getByText(/target ≤ ~5h/)).toBeInTheDocument()
  })

  it("names the AGENTS.md bundle for the Codex agent", () => {
    render(
      <DemoDayHandoffPanel
        verdict={verdict()}
        stages={stagesAt(1)}
        targetAgent="codex"
        onDownloadBundle={vi.fn()}
      />,
    )
    expect(
      screen.getByRole("button", { name: /Download handoff bundle for AGENTS\.md/ }),
    ).toBeInTheDocument()
  })

  it("lists the named construction gaps when the verifier found them", () => {
    const v = verdict({
      verified: false,
      checks: {
        ...verdict().checks,
        C3: {
          name: "ac_to_test",
          passed: false,
          gaps: ["AC-002 is absent from the harness ## Requirement-to-Test Matrix"],
        },
      },
    })
    render(
      <DemoDayHandoffPanel
        verdict={v}
        stages={stagesAt(1)}
        targetAgent="claude_code"
        onDownloadBundle={vi.fn()}
      />,
    )
    expect(screen.getByText("1 gap")).toBeInTheDocument()
    expect(
      screen.getByText("Every acceptance criterion has a test"),
    ).toBeInTheDocument()
    expect(screen.getByText(/AC-002 is absent/)).toBeInTheDocument()
  })

  it("warns when the verdict is stale and re-runs on download", () => {
    render(
      <DemoDayHandoffPanel
        verdict={verdict()}
        stages={stagesAt(2)}
        targetAgent="claude_code"
        onDownloadBundle={vi.fn()}
      />,
    )
    expect(screen.getByText("Out of date")).toBeInTheDocument()
    expect(screen.getByText(/re-run automatically when you download/)).toBeInTheDocument()
  })

  it("explains the pending state and disables download until finalised", () => {
    const onDownload = vi.fn()
    render(
      <DemoDayHandoffPanel
        verdict={null}
        stages={stagesAt(1)}
        targetAgent="claude_code"
        onDownloadBundle={onDownload}
        downloadDisabled
        downloadDisabledReason="Finalise all four stages to download the handoff bundle."
      />,
    )
    expect(screen.getByText("Pending")).toBeInTheDocument()
    expect(
      screen.getByText(/Finalise all four stages to run the build check/),
    ).toBeInTheDocument()
    const button = screen.getByRole("button", { name: /Download handoff bundle/ })
    expect(button).toBeDisabled()
    fireEvent.click(button)
    expect(onDownload).not.toHaveBeenCalled()
  })

  it("fires the download callback when enabled", () => {
    const onDownload = vi.fn()
    render(
      <DemoDayHandoffPanel
        verdict={verdict()}
        stages={stagesAt(1)}
        targetAgent="claude_code"
        onDownloadBundle={onDownload}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: /Download handoff bundle/ }))
    expect(onDownload).toHaveBeenCalledOnce()
  })
})

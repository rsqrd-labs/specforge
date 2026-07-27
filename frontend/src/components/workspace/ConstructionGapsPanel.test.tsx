import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ConstructionGapsPanel } from "./ConstructionGapsPanel"
import type { Stage, StageType } from "../../types/stage"
import type { ConstructionVerdict } from "../../types/workspace"

const STAGE_TYPES: StageType[] = ["spec", "plan", "harness", "tasks"]

function stagesAt(version: number): Pick<Stage, "type" | "current_version">[] {
  return STAGE_TYPES.map((type) => ({ type, current_version: version }))
}

/** A standard-mode verdict: standard check names, null Demo Day calibration. */
function verdict(overrides: Partial<ConstructionVerdict> = {}): ConstructionVerdict {
  return {
    verified: true,
    checks: {
      C1: { name: "requirement_coverage", passed: true, gaps: [], advisory: false },
      C2: { name: "test_coverage", passed: true, gaps: [], advisory: false },
      C3: { name: "dag_acyclic", passed: true, gaps: [], advisory: false },
      C4: { name: "plan_coverage", passed: true, gaps: [], advisory: false },
      C5: { name: "e2e_reachable", passed: true, gaps: [], advisory: false },
      C6: { name: "task_inventory", passed: true, gaps: [], advisory: true },
    },
    estimated_minutes: null,
    time_budget_minutes: null,
    stage_versions: { spec: 1, plan: 1, harness: 1, tasks: 1 },
    ...overrides,
  }
}

describe("ConstructionGapsPanel", () => {
  it("renders nothing before the verifier has run", () => {
    const { container } = render(
      <ConstructionGapsPanel verdict={null} stages={stagesAt(1)} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("names every gap of every failing check", () => {
    const v = verdict({
      checks: {
        ...verdict().checks,
        C2: {
          name: "test_coverage",
          passed: false,
          gaps: ["harness test `test_login` is referenced by no task"],
          advisory: false,
        },
        C4: {
          name: "plan_coverage",
          passed: false,
          gaps: ["no task cites `## Deployment and Operations`"],
          advisory: false,
        },
      },
    })
    render(<ConstructionGapsPanel verdict={v} stages={stagesAt(1)} />)
    expect(screen.getByText("2 gaps")).toBeInTheDocument()
    expect(
      screen.getByText("Every harness test is built by a task"),
    ).toBeInTheDocument()
    expect(
      screen.getByText("Every load-bearing plan section is implemented"),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/test_login. is referenced by no task/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/no task cites .## Deployment and Operations./),
    ).toBeInTheDocument()
  })

  it("names an un-enforced failure too — the flag governs `verified`, not disclosure", () => {
    const v = verdict({
      checks: {
        ...verdict().checks,
        C1: {
          name: "requirement_coverage",
          passed: false,
          gaps: ["FR-003 is not claimed by any task"],
          advisory: false,
          enforced: false,
        },
      },
    })
    render(<ConstructionGapsPanel verdict={v} stages={stagesAt(1)} />)
    expect(screen.getByText("1 gap")).toBeInTheDocument()
    expect(screen.getByText(/FR-003 is not claimed/)).toBeInTheDocument()
  })

  it("never counts an advisory check as a gap", () => {
    const v = verdict({
      checks: {
        ...verdict().checks,
        C6: {
          name: "task_inventory",
          passed: false,
          gaps: ["6 task blocks for 20 requirements"],
          advisory: true,
        },
      },
    })
    render(<ConstructionGapsPanel verdict={v} stages={stagesAt(1)} />)
    expect(screen.getByText("Verified ✓")).toBeInTheDocument()
    expect(screen.queryByText(/6 task blocks/)).not.toBeInTheDocument()
  })

  it("reports a stale verdict rather than a green tick", () => {
    render(<ConstructionGapsPanel verdict={verdict()} stages={stagesAt(2)} />)
    expect(screen.getByText("Out of date")).toBeInTheDocument()
    expect(screen.queryByText("Verified ✓")).not.toBeInTheDocument()
  })

  it("does not imply a build-time estimate standard mode never produces", () => {
    render(<ConstructionGapsPanel verdict={verdict()} stages={stagesAt(1)} />)
    expect(screen.queryByText(/target ≤/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Estimated build time/)).not.toBeInTheDocument()
  })
})

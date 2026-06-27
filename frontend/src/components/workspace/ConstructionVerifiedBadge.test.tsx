import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ConstructionVerifiedBadge } from "./ConstructionVerifiedBadge"
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
    regen_attempted: false,
    ...overrides,
  }
}

describe("ConstructionVerifiedBadge", () => {
  it("renders nothing when there is no verdict yet", () => {
    const { container } = render(
      <ConstructionVerifiedBadge verdict={null} stages={stagesAt(1)} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("shows the verified ✓ badge when the verdict matches the live versions", () => {
    render(<ConstructionVerifiedBadge verdict={verdict()} stages={stagesAt(1)} />)
    expect(screen.getByText(/Construction-verified ✓/)).toBeInTheDocument()
  })

  it("counts only the C1–C4 gaps, never the advisory C5", () => {
    const v = verdict({
      verified: false,
      checks: {
        C1: { name: "dag_acyclic", passed: true, gaps: [] },
        C2: { name: "task_to_test", passed: false, gaps: ["T-003: bad ref"] },
        C3: { name: "ac_to_test", passed: false, gaps: ["AC-002 absent", "AC-003 absent"] },
        C4: { name: "e2e_reachable", passed: true, gaps: [] },
        // C5 fails but must NOT be counted in the badge.
        C5: { name: "time_budget", passed: false, gaps: ["over budget"] },
      },
    })
    render(<ConstructionVerifiedBadge verdict={v} stages={stagesAt(1)} />)
    expect(screen.getByText("3 gaps")).toBeInTheDocument()
  })

  it("never renders green when the verdict is stale, even if verified is true", () => {
    // A stage was refined past the stamped version → stale. The verified flag is
    // true, but a stale verdict must read as out-of-date, not as a false green.
    render(
      <ConstructionVerifiedBadge verdict={verdict()} stages={stagesAt(2)} />,
    )
    expect(screen.getByText(/Verdict out of date/)).toBeInTheDocument()
    expect(screen.queryByText(/Construction-verified/)).not.toBeInTheDocument()
  })
})

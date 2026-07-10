import { describe, expect, it } from "vitest"

import {
  extractTaskFrontMatter,
  formatEffortSummaryChip,
  parseEffortSummary,
  parseTaskBlocks,
} from "./tasksParser"

const CLEAN_BLOCK = `## Effort Summary

- Estimate range: ~3 weeks
- Tasks: 15 total · 6 MUST · 7 SHOULD · 2 COULD
- Sizes: 2xL · 8xM · 5xS
- Minimum cut: Ship MUST-only → ~10 days

## Execution Overview

Some other content here. This must not bleed into the parser.

## Phase 1

### T-001: Bootstrap

**Priority:** MUST
**Estimate:** S
`

describe("parseEffortSummary", () => {
  it("returns the structured summary for clean content", () => {
    const result = parseEffortSummary(CLEAN_BLOCK)
    expect(result).not.toBeNull()
    expect(result).toMatchObject({
      estimateRange: "~3 weeks",
      totalTasks: 15,
      mustCount: 6,
      shouldCount: 7,
      couldCount: 2,
      minimumCut: "Ship MUST-only → ~10 days",
    })
    expect(result?.sizesLine).toContain("2xL")
  })

  it("returns null when the block is missing entirely", () => {
    const result = parseEffortSummary(
      "## Execution Overview\n\nNo summary here.\n\n### T-001: Something\n",
    )
    expect(result).toBeNull()
  })

  it("returns null on malformed lines without throwing", () => {
    const malformed = `## Effort Summary

- Estimate range: ~3 weeks
- Tasks: this line is broken
- Sizes: 1xS

## Next
`
    // Missing total + minimum-cut line — must return null, not throw.
    expect(() => parseEffortSummary(malformed)).not.toThrow()
    expect(parseEffortSummary(malformed)).toBeNull()
  })

  it("returns null for empty input", () => {
    expect(parseEffortSummary("")).toBeNull()
    // @ts-expect-error — exercises the runtime guard
    expect(parseEffortSummary(null)).toBeNull()
  })

  it("does not pick up MUST counts from later task bodies", () => {
    // Regression: ensure the parser scopes to the Effort Summary section, so
    // a downstream task that happens to mention "9 MUST" in prose doesn't
    // overwrite the real count.
    const sneaky = `## Effort Summary

- Estimate range: ~1 week
- Tasks: 3 total · 1 MUST
- Sizes: 3xS
- Minimum cut: Ship MUST-only → ~1 day

## Phase 1

### T-001: ...

**Description**
This task involves 9 MUST decisions about the API.
`
    const result = parseEffortSummary(sneaky)
    expect(result?.mustCount).toBe(1)
    expect(result?.totalTasks).toBe(3)
  })

  it("tolerates bolded labels", () => {
    const bold = `## Effort Summary

- **Estimate range:** ~2 weeks
- **Tasks:** 8 total · 4 MUST · 4 SHOULD
- **Sizes:** 4xM · 4xS
- **Minimum cut:** Ship MUST-only → ~5 days
`
    const result = parseEffortSummary(bold)
    expect(result?.estimateRange).toBe("~2 weeks")
    expect(result?.mustCount).toBe(4)
  })
})

// Matches the exact per-task shape from backend/prompts/tasks.py's
// SYSTEM_PROMPT — the ground truth for what the LLM is instructed to emit.
const TASKS_DOC = `## Effort Summary

- Estimate range: ~3 weeks
- Tasks: 2 total · 1 MUST · 1 SHOULD
- Sizes: 1xM · 1xS
- Minimum cut: Ship MUST-only → ~3 days

## Traceability Overview

Some overview text that must not be parsed as a task.

## Phase 1: API Layer

### T-015: Implement subscription cancellation endpoint

**Phase:** API Layer
**Spec refs:** FR-012, SEC-004, NFR-003
**Plan refs:** Subscriptions API §DELETE /subscriptions/{id}
**Harness refs:** \`tests/integration/test_subscriptions.py::TestCancellation::test_cancel_transitions_to_grace_period\`
**Priority:** MUST
**Estimate:** M
**Estimated size:** M
**Risk:** Medium — incorrect state transition could allow continued billing
**Owner:** Backend

**Description**
Implement DELETE /subscriptions/{id} transitioning an active subscription to grace_period.

**Inputs**
- \`src/models/subscription.py\` from T-008

**Outputs**
- Modified: \`src/routers/subscriptions.py\` — DELETE handler added

**Steps**
1. Add \`cancel()\` to \`src/services/subscription_service.py\`.
2. Add \`DELETE /subscriptions/{id}\` handler.

**Acceptance Criteria**
1. \`pytest tests/integration/test_subscriptions.py::TestCancellation -v\` passes.

**Rollback / Recovery**
State change is in the DB. To undo: \`UPDATE subscriptions SET state='active' WHERE id='<id>'\`.

**Dependencies**
T-008, T-010, T-012

### T-016: Send cancellation receipt email

**Priority:** SHOULD
**Estimate:** S

**Description**
Enqueue a cancellation receipt email once T-015 completes.

**Dependencies**
T-015
`

describe("parseTaskBlocks", () => {
  it("parses every metadata and body field from a well-formed task", () => {
    const blocks = parseTaskBlocks(TASKS_DOC)
    expect(blocks).toHaveLength(2)

    const first = blocks[0]
    expect(first.id).toBe("T-015")
    expect(first.title).toBe("Implement subscription cancellation endpoint")
    expect(first.phase).toBe("API Layer")
    expect(first.priority).toBe("MUST")
    expect(first.estimate).toBe("M")
    expect(first.estimatedSize).toBe("M")
    expect(first.owner).toBe("Backend")
    expect(first.risk).toContain("incorrect state transition")
    expect(first.specRefs).toContain("FR-012")
    expect(first.description).toContain("grace_period")
    expect(first.steps).toContain("cancel()")
    expect(first.acceptanceCriteria).toContain("pytest tests/integration")
    expect(first.rollback).toContain("UPDATE subscriptions")
    expect(first.dependencies).toEqual(["T-008", "T-010", "T-012"])
  })

  it("does not bleed one task's fields into the next", () => {
    const blocks = parseTaskBlocks(TASKS_DOC)
    const second = blocks[1]
    expect(second.id).toBe("T-016")
    expect(second.priority).toBe("SHOULD")
    expect(second.phase).toBeNull()
    expect(second.description).toContain("T-015 completes")
    expect(second.description).not.toContain("subscription cancellation endpoint")
    expect(second.dependencies).toEqual(["T-015"])
  })

  it("returns an empty array (never throws) for content with no task headings", () => {
    expect(() => parseTaskBlocks("## Just a heading\n\nNo tasks here.")).not.toThrow()
    expect(parseTaskBlocks("## Just a heading\n\nNo tasks here.")).toEqual([])
    expect(parseTaskBlocks("")).toEqual([])
    // @ts-expect-error — exercises the runtime guard
    expect(parseTaskBlocks(null)).toEqual([])
  })

  it("defaults dependencies to an empty array when the section is absent", () => {
    const noDeps = `### T-001: Standalone setup task

**Priority:** MUST
**Estimate:** S

**Description**
First task in the plan; nothing precedes it.
`
    const [task] = parseTaskBlocks(noDeps)
    expect(task.dependencies).toEqual([])
  })
})

describe("extractTaskFrontMatter", () => {
  it("returns everything before the first task heading", () => {
    const front = extractTaskFrontMatter(TASKS_DOC)
    expect(front).toContain("Effort Summary")
    expect(front).toContain("Traceability Overview")
    expect(front).not.toContain("T-015")
  })

  it("returns the whole document when there is no task heading", () => {
    const doc = "## Effort Summary\n\nNo tasks yet.\n"
    expect(extractTaskFrontMatter(doc)).toBe(doc)
  })
})

describe("formatEffortSummaryChip", () => {
  it("renders the three-glyph chip text", () => {
    const text = formatEffortSummaryChip({
      estimateRange: "~3 weeks",
      totalTasks: 15,
      mustCount: 6,
      shouldCount: 7,
      couldCount: 2,
      sizesLine: "2xL · 8xM · 5xS",
      minimumCut: "Ship MUST-only → ~10 days",
    })
    expect(text).toBe("~3 weeks · 15 tasks · 6 MUST")
  })
})

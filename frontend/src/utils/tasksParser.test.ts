import { describe, expect, it } from "vitest"

import {
  formatEffortSummaryChip,
  parseEffortSummary,
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

/**
 * Parser for the `## Effort Summary` block emitted at the top of TASKS.md by
 * T-USE-05's prompt update. Returns `null` for missing, partial, or malformed
 * content so older finalised tasks (generated before T-164) degrade silently
 * — the workspace chip simply hides.
 *
 * The parser is intentionally tolerant of leading list markers (`- `, `* `)
 * and bold emphasis around the label, since LLM output drifts on whitespace.
 */

export interface EffortSummary {
  /** Calendar-week span text, e.g. `~3 weeks`. */
  estimateRange: string
  /** Total task count. */
  totalTasks: number
  /** Count of tasks marked `Priority: MUST`. */
  mustCount: number
  /** Count of tasks marked `Priority: SHOULD`. */
  shouldCount: number
  /** Count of tasks marked `Priority: COULD`. */
  couldCount: number
  /** Raw "AxXL · BxL · …" string, kept verbatim for tooltip rendering. */
  sizesLine: string
  /** Calendar-day span for the MUST-only subset, e.g. `~10 days`. */
  minimumCut: string
}

const SUMMARY_HEADING = /^##\s+Effort\s+Summary\s*$/im
// Lines start optionally with a list marker, then optional bold around the
// label, then the label, then a colon. The colon may sit *inside* the bold
// span (`**Estimate range:**`) so the captured value can begin with `**` —
// we strip it after the match.
const ESTIMATE_RANGE_RE = /^[\s\-*]*\*{0,2}\s*Estimate\s*range\s*:\s*(.+?)\s*$/im
const TASKS_LINE_RE = /^[\s\-*]*\*{0,2}\s*Tasks\s*:\s*(.+?)\s*$/im
const SIZES_LINE_RE = /^[\s\-*]*\*{0,2}\s*Sizes\s*:\s*(.+?)\s*$/im
const MIN_CUT_LINE_RE = /^[\s\-*]*\*{0,2}\s*Minimum\s+cut\s*:\s*(.+?)\s*$/im

const LEADING_BOLD_RE = /^\*+\s*/

function stripBold(value: string): string {
  return value.replace(LEADING_BOLD_RE, "").replace(/\s*\*+$/, "").trim()
}

const TOTAL_COUNT_RE = /(\d+)\s*total/i
const MUST_COUNT_RE = /(\d+)\s*MUST/
const SHOULD_COUNT_RE = /(\d+)\s*SHOULD/
const COULD_COUNT_RE = /(\d+)\s*COULD/

function findSummarySection(content: string): string | null {
  const headingMatch = SUMMARY_HEADING.exec(content)
  if (!headingMatch) return null
  // Slice from the heading to the next `## ` (next top-level section) so the
  // counter regexes don't pick up MUST/SHOULD/COULD lines from later tasks.
  const sliceStart = headingMatch.index + headingMatch[0].length
  const remainder = content.slice(sliceStart)
  const nextHeading = remainder.search(/^##\s+/m)
  return nextHeading === -1 ? remainder : remainder.slice(0, nextHeading)
}

export function parseEffortSummary(content: string): EffortSummary | null {
  if (!content || typeof content !== "string") return null

  try {
    const section = findSummarySection(content)
    if (section === null) return null

    const estimateMatch = ESTIMATE_RANGE_RE.exec(section)
    const tasksMatch = TASKS_LINE_RE.exec(section)
    const sizesMatch = SIZES_LINE_RE.exec(section)
    const minCutMatch = MIN_CUT_LINE_RE.exec(section)

    if (!estimateMatch || !tasksMatch || !sizesMatch || !minCutMatch) {
      return null
    }

    const tasksLine = tasksMatch[1]
    const totalMatch = TOTAL_COUNT_RE.exec(tasksLine)
    const mustMatch = MUST_COUNT_RE.exec(tasksLine)

    if (!totalMatch) return null

    const totalTasks = parseInt(totalMatch[1], 10)
    if (Number.isNaN(totalTasks) || totalTasks < 0) return null

    // MUST/SHOULD/COULD counts are optional individually — a list of all-MUST
    // tasks will not include "0 SHOULD". Missing means zero.
    const mustCount = mustMatch ? parseInt(mustMatch[1], 10) : 0
    const shouldMatch = SHOULD_COUNT_RE.exec(tasksLine)
    const couldMatch = COULD_COUNT_RE.exec(tasksLine)
    const shouldCount = shouldMatch ? parseInt(shouldMatch[1], 10) : 0
    const couldCount = couldMatch ? parseInt(couldMatch[1], 10) : 0

    if ([mustCount, shouldCount, couldCount].some(Number.isNaN)) return null

    return {
      estimateRange: stripBold(estimateMatch[1]),
      totalTasks,
      mustCount,
      shouldCount,
      couldCount,
      sizesLine: stripBold(sizesMatch[1]),
      minimumCut: stripBold(minCutMatch[1]),
    }
  } catch {
    // The contract requires the parser never throws.
    return null
  }
}

/**
 * Render a parsed EffortSummary as the single-line chip text:
 * `~3 weeks · 15 tasks · 6 MUST`.
 */
export function formatEffortSummaryChip(summary: EffortSummary): string {
  return `${summary.estimateRange} · ${summary.totalTasks} tasks · ${summary.mustCount} MUST`
}

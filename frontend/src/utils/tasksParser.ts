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

// ---------------------------------------------------------------------------
// Per-task block parser (T-USE-05 task schema — see prompts/tasks.py
// SYSTEM_PROMPT for the authoritative field list). Renders TASKS.md as
// collapsible cards instead of one continuous scroll (2026-07 design review
// remediation: "Tasks throws away its own structure").
// ---------------------------------------------------------------------------

export interface TaskBlock {
  id: string
  title: string
  phase: string | null
  priority: string | null
  estimate: string | null
  estimatedSize: string | null
  risk: string | null
  owner: string | null
  specRefs: string | null
  planRefs: string | null
  harnessRefs: string | null
  /** Markdown body for each named section, verbatim (still needs
   *  MarkdownRenderer for code fences / inline code). Absent sections are
   *  omitted rather than shown empty. */
  description: string | null
  inputs: string | null
  outputs: string | null
  steps: string | null
  acceptanceCriteria: string | null
  rollback: string | null
  /** Dependency task IDs, e.g. ["T-008", "T-010"]. Empty when none/absent. */
  dependencies: string[]
  /** The full, untouched markdown for this task — always renderable even if
   *  a field above failed to extract, so no content is ever lost. */
  raw: string
}

const TASK_HEADING_RE = /^###\s+(T-\d+)\s*:\s*(.+?)\s*$/im
const NEXT_BOUNDARY_RE = /^(?:###\s+T-\d+\s*:|##\s+)/m

const METADATA_FIELDS: Array<[keyof TaskBlock, string]> = [
  ["phase", "Phase"],
  ["priority", "Priority"],
  ["estimate", "Estimate"],
  ["estimatedSize", "Estimated\\s+size"],
  ["risk", "Risk"],
  ["owner", "Owner"],
  ["specRefs", "Spec\\s+refs"],
  ["planRefs", "Plan\\s+refs"],
  ["harnessRefs", "Harness\\s+refs"],
]

const BODY_SECTIONS: Array<[keyof TaskBlock, string]> = [
  ["description", "Description"],
  ["inputs", "Inputs"],
  ["outputs", "Outputs"],
  ["steps", "Steps"],
  ["acceptanceCriteria", "Acceptance\\s+Criteria"],
  ["rollback", "Rollback\\s*/\\s*Recovery"],
  ["dependencies", "Dependencies"],
]

function extractMetadataField(body: string, label: string): string | null {
  const re = new RegExp(`^[\\s\\-*]*\\*{0,2}\\s*${label}\\s*:\\*{0,2}\\s*(.+?)\\s*$`, "im")
  const match = re.exec(body)
  return match ? stripBold(match[1]) : null
}

/** Slices the markdown from one `**Section**` header to the next known
 *  header (or the end of the task body), matching the same header-only-line
 *  convention the effort-summary parser relies on above. */
function extractBodySection(body: string, label: string): string | null {
  const headingRe = new RegExp(`^\\*{1,2}${label}\\*{1,2}\\s*$`, "im")
  const match = headingRe.exec(body)
  if (!match || match.index === undefined) return null

  const afterHeading = body.slice(match.index + match[0].length)
  const otherHeadings = BODY_SECTIONS.map(([, l]) => l).filter((l) => l !== label)
  const nextHeadingRe = new RegExp(`^\\*{1,2}(?:${otherHeadings.join("|")})\\*{1,2}\\s*$`, "im")
  const next = nextHeadingRe.exec(afterHeading)
  const section = next ? afterHeading.slice(0, next.index) : afterHeading
  const trimmed = section.trim()
  return trimmed.length > 0 ? trimmed : null
}

const DEPENDENCY_ID_RE = /T-\d+/g

function parseSingleTaskBlock(raw: string): TaskBlock | null {
  const headingMatch = TASK_HEADING_RE.exec(raw)
  if (!headingMatch) return null

  const block: Partial<TaskBlock> = { id: headingMatch[1], title: headingMatch[2] }
  for (const [key, label] of METADATA_FIELDS) {
    ;(block as Record<string, unknown>)[key] = extractMetadataField(raw, label)
  }
  for (const [key, label] of BODY_SECTIONS) {
    if (key === "dependencies") continue
    ;(block as Record<string, unknown>)[key] = extractBodySection(raw, label)
  }
  const dependenciesSection = extractBodySection(raw, "Dependencies")
  block.dependencies = dependenciesSection
    ? Array.from(dependenciesSection.matchAll(DEPENDENCY_ID_RE)).map((m) => m[0])
    : []
  block.raw = raw.trim()

  return block as TaskBlock
}

/**
 * Splits TASKS.md into individual task blocks. Returns `[]` (never throws)
 * when the content doesn't contain the `### T-NNN:` heading shape at all —
 * callers should fall back to plain markdown rendering in that case, the
 * same degrade-silently contract `parseEffortSummary` uses for older content.
 */
export function parseTaskBlocks(content: string): TaskBlock[] {
  if (!content || typeof content !== "string") return []

  try {
    const headingRe = /^###\s+T-\d+\s*:.*$/gm
    const starts: number[] = []
    let m: RegExpExecArray | null
    while ((m = headingRe.exec(content)) !== null) {
      starts.push(m.index)
    }
    if (starts.length === 0) return []

    const blocks: TaskBlock[] = []
    for (let i = 0; i < starts.length; i++) {
      const start = starts[i]
      const afterHeadingLine = content.indexOf("\n", start) + 1 || content.length
      const rest = content.slice(afterHeadingLine)
      const boundary = NEXT_BOUNDARY_RE.exec(rest)
      const end = afterHeadingLine + (boundary ? boundary.index : rest.length)
      const raw = content.slice(start, end)
      const parsed = parseSingleTaskBlock(raw)
      if (parsed) blocks.push(parsed)
    }
    return blocks
  } catch {
    // Never throws — an unparseable document just falls back to plain markdown.
    return []
  }
}

/**
 * The markdown before the first `### T-NNN:` heading — Effort Summary,
 * Traceability Overview, Dependency Graph, and the first `## Phase` heading.
 * Rendered as-is via MarkdownRenderer above the task cards.
 */
export function extractTaskFrontMatter(content: string): string {
  const headingRe = /^###\s+T-\d+\s*:/m
  const match = headingRe.exec(content)
  if (!match || match.index === undefined) return content
  return content.slice(0, match.index).trim()
}

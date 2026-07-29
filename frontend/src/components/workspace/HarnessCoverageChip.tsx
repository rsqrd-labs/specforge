interface CoverageSummary {
  tests: number
  covered: number
  total: number
  percent: number
}

interface HarnessCoverageChipProps {
  coverage_summary: CoverageSummary | null | undefined
}

export function HarnessCoverageChip({
  coverage_summary,
}: HarnessCoverageChipProps) {
  if (!coverage_summary) return null

  const pct = Math.max(0, Math.min(100, coverage_summary.percent))
  if (pct < 100) return null

  // `percent` is the deterministic matrix→file coverage the backend computes
  // from the harness itself (artifact_validator.harness_coverage_ratio): every
  // requirement the Requirement-to-Test Matrix maps to a test file has at least
  // one of those files actually emitted. `tests`/`covered`/`total` are NOT real
  // counts — the batch coverage query reads only the stored percentage and fills
  // them as `tests=0, covered=pct, total=100`, so the old tooltip rendered the
  // flat falsehood "0 tests cover all 100 spec requirements" on every full-
  // coverage chip. Describe what the number actually measures instead.
  const tooltip =
    "Every requirement in the harness's Requirement-to-Test Matrix has at least one generated test file."

  return (
    <span
      className="harness-coverage-chip is-full"
      title={tooltip}
      aria-label="Full harness coverage"
    >
      ✓ Full coverage
    </span>
  )
}

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

  const tooltip = `${coverage_summary.tests} tests cover all ${coverage_summary.total} spec requirements.`

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

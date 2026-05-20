interface CoverageSummary {
  tests: number
  covered: number
  total: number
  percent: number
}

interface HarnessCoverageChipProps {
  coverage_summary: CoverageSummary | null | undefined
}

/**
 * T-USE-13 — harness coverage chip.
 *
 * Single component used in three places: workspace header, dashboard card,
 * and public view. The visual treatment must stay identical across all
 * three; the chip carries a product-level meaning ("the spec is backed
 * by tests") and that signal only holds if it reads the same everywhere.
 *
 * Hidden when null — the chip is a *result* signal, not a *progress*
 * signal. Below 80% the text turns to a warm warning tone (no new colour:
 * we use a darker saffron tint that already lives in the palette via
 * eval-warning treatment). Below 60% there is no special treatment beyond
 * what the eval panel already shows.
 */
export function HarnessCoverageChip({
  coverage_summary,
}: HarnessCoverageChipProps) {
  if (!coverage_summary) return null

  const pct = Math.max(0, Math.min(100, coverage_summary.percent))
  const warning = pct < 80
  const label =
    coverage_summary.total > 0
      ? `${coverage_summary.covered} / ${coverage_summary.total} reqs`
      : `${pct}%`
  const tooltip = `${coverage_summary.tests} tests cover ${coverage_summary.covered} of ${coverage_summary.total} spec requirements. SpecForge generates the tests; you ship them.`

  return (
    <span
      className={`harness-coverage-chip ${warning ? "is-warning" : ""}`}
      title={tooltip}
      aria-label={`Harness coverage: ${pct}%`}
    >
      <span className="harness-coverage-chip-bar" aria-hidden="true">
        <span
          className="harness-coverage-chip-fill"
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="harness-coverage-chip-count">{label}</span>
      <span className="harness-coverage-chip-suffix">covered</span>
    </span>
  )
}

# Harness Coverage Integrity (core-generation idiot-proofing)

## Why

Diagnosed on the one real workspace (`AWS CUR analyser`). Its harness scored as
"lots of missing coverage" in the UI, which read as a product defect. Root-cause
analysis found the negative view was sitting on top of **two real
core-generation defects** plus a **mislabelled coverage signal**:

1. **Duplicated harness.** The cheap-tier model emitted the entire `## Files`
   section twice — a 122 KB artifact that was an exact doubling of ~61 KB
   (`schemas.test.ts` and every other file appeared as two `### File:` blocks).
   Nothing detected it.
2. **Matrix referenced an unemitted file.** The Requirement-to-Test Matrix mapped
   `NFR-001`/`NFR-002` to `tests/performance/performance_budget.test.ts`, which
   was never emitted in `## Files` (and was absent from the File Tree too, so the
   existing tree→files check also missed it). Those two requirements were
   genuinely untested. The validator's matrix check keyed on the pytest `test_`
   prefix / `def test_`, so it **silently no-opped** on this TypeScript/Vitest
   harness (`it(...)` × 106, `def test_` × 0) — and on every Go/Ruby/JS harness.
3. **Coverage signal lied.** `extract_deferred_reqs` scraped requirement IDs out
   of `TestCategoryGap` *category-depth* records and surfaced them as
   "Expand Test Coverage — N optional". 7 of the 9 listed requirements already
   had emitted tests; the paid patch would have re-tested covered requirements.

## Fixes (all deterministic, zero-LLM)

- **Self-heal duplication** — `dedupe_file_blocks()` drops duplicate
  `### File:` blocks (keeping the first) at the single finalization chokepoint in
  `StageManager.generate()`, before any gate or persistence. No repair, no
  credit. Metric: `specforge_pipeline_harness_file_dedup_total{provider}`.
- **Language-agnostic matrix→file integrity** — a new `harness_matrix_missing_file`
  completeness finding: every test *file path* the matrix backticks must exist as
  a `### File:` block. Catches the missing perf file on any test framework.
  Advisory (non-refundable) — informs, never false-refunds.
- **Honest coverage signal** — `extract_deferred_reqs` now delegates to
  `uncovered_requirements()`, which reports a requirement as a gap only when
  **every** matrix-mapped test file for it is absent from `## Files`. For AWS CUR
  this collapses the bogus 9 to the 2 real gaps (`NFR-001`, `NFR-002`); for a
  fully-emitted harness it returns `[]` (no false "missing coverage" panel). The
  paid patch now only ever regenerates tests that genuinely do not exist.
- **UI** — the `deferred_reqs` panel is relabelled "Missing Test Coverage"
  (warning styling), not "Expand Test Coverage — N optional".

## Verification

- `dedupe_file_blocks` on the real AWS CUR harness: 32 → 16 File blocks,
  122 KB → 67 KB.
- `harness_matrix_missing_file` fires on it for
  `tests/performance/performance_budget.test.ts`.
- `extract_deferred_reqs`: 9 (mostly covered) → `['NFR-001', 'NFR-002']`; `[]`
  for a clean harness.
- Full backend suite green (1495 passed, 80.26% cov); full frontend green
  (376 passed); tsc clean. Harness-contract failures are pre-existing
  (identical on clean HEAD).

## Not done here (next step, needs a product call)

The matrix check is advisory. If a missing baseline test file should *block*
finalisation (rather than surface as advisory + offer a paid patch), that is a
policy decision on top of this deterministic foundation.

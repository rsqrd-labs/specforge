import { useEffect, useMemo } from "react"

import { featureFlags } from "../../config/featureFlags"
import type {
  EstimateLookupOperation,
  GenerationEstimate,
} from "../../services/api"
import { useGenerationEstimatesStore } from "../../store/generationEstimatesStore"
import type { StageType } from "../../types/stage"
import type { AIProvider } from "../../types/workspace"
import type { GenerationActivityOperation } from "./StreamingOverlay"

/**
 * Issue #21 — Phase 2a: honest, client-only ETA.
 *
 * An estimate is a banded duration, never a single false-precision number:
 * `p50` is the typical time, `p90` the slow-tail mark past which we tell the
 * user we're "still working".
 *
 * These baselines are a **constant heuristic table** with zero backend
 * dependency — instant and reliable. Phase 2b replaces the lookup with live,
 * aggregate percentiles from `GET /stages/generation-estimates` and falls back
 * to this exact table on any error/empty/low-sample response, so the contract
 * here (`{ p50, p90 }` in seconds) is the stable seam.
 */
export interface EtaEstimate {
  /** Typical (median) completion time, in seconds. */
  p50: number
  /** Slow-tail completion time, in seconds; past this we say "still working". */
  p90: number
}

/**
 * Provenance of a resolved estimate. `"live"` means the band came from real,
 * per-provider aggregate percentiles; `"heuristic"` means the hard-coded guess
 * table. The loading UI only ever shows a *number* on a `"live"` estimate — the
 * guess table is honest enough to narrate a wait but not to make a time promise
 * (issue #48). With no production traffic every estimate is `"heuristic"`, so the
 * number stays hidden until real data accumulates.
 */
export type EtaSource = "live" | "heuristic"

/** An `EtaEstimate` plus where it came from. */
export interface ResolvedEta extends EtaEstimate {
  source: EtaSource
}

/**
 * Fresh full-stage generation baselines. Spec is the cheapest stage; harness
 * (validation scaffolding) the most expensive. Generations here run into
 * minutes under the watchdog (180s idle / 900s hard cap), so the past-p90 copy
 * must never imply "almost done" — the band stays "still working".
 */
const STAGE_GENERATE: Record<StageType, EtaEstimate> = {
  spec: { p50: 30, p90: 75 },
  plan: { p50: 45, p90: 100 },
  harness: { p50: 60, p90: 130 },
  tasks: { p50: 50, p90: 110 },
}

/** A safe default when the stage type is unknown (forward-compat / bad input). */
const FALLBACK_ESTIMATE: EtaEstimate = STAGE_GENERATE.plan

/** A focused refinement edits a selection, not the whole artifact — small and
 *  roughly stage-independent. */
const FOCUSED_PATCH_ESTIMATE: EtaEstimate = { p50: 18, p90: 45 }

/** A gap regenerate repairs missing coverage on top of an existing stage, so it
 *  is materially cheaper than a full (re)generation of that stage. */
const GAP_PATCH_SCALE = 0.6

function scaleEstimate(estimate: EtaEstimate, factor: number): EtaEstimate {
  return {
    p50: Math.max(1, Math.round(estimate.p50 * factor)),
    p90: Math.max(1, Math.round(estimate.p90 * factor)),
  }
}

/**
 * Pure baseline lookup: maps a (stage, operation) to its `{ p50, p90 }` band.
 * Total over the input space — an unknown stage falls back to a sane default
 * rather than throwing, because this drives a loading screen and must never be
 * the thing that breaks.
 */
export function estimateEta(
  stageType: StageType | null | undefined,
  operation: GenerationActivityOperation | null | undefined,
): EtaEstimate {
  const base = (stageType && STAGE_GENERATE[stageType]) || FALLBACK_ESTIMATE

  switch (operation) {
    case "focused-patch":
      return FOCUSED_PATCH_ESTIMATE
    case "regenerate-gaps":
      return scaleEstimate(base, GAP_PATCH_SCALE)
    case "generate":
    case "regenerate":
    case "quality-gate-regenerate":
    default:
      // A full (re)generation, or an unknown op: treat as a full stage run.
      return base
  }
}

/**
 * Collapse the five activity operations into the three lookup buckets the live
 * estimates endpoint serves — the SAME grouping `estimateEta` applies above, so
 * a live hit and the heuristic fallback share one key space. A full
 * (re)generation (`generate` / `regenerate` / `quality-gate-regenerate`) all map
 * to `generate`; the two patch flows keep their own buckets.
 */
export function canonicalLookupOperation(
  operation: GenerationActivityOperation | null | undefined,
): EstimateLookupOperation {
  switch (operation) {
    case "focused-patch":
      return "focused-patch"
    case "regenerate-gaps":
      return "regenerate-gaps"
    default:
      return "generate"
  }
}

/**
 * Prefer the live, data-backed band for this (provider, stage, operation); fall
 * back to the constant heuristic table on any miss. Pure — the live data is
 * passed in, not fetched here, so it stays unit-testable. The backend already
 * filters by sample count and sanity-bounds the durations, so any served entry
 * is trustworthy; we still guard the shape defensively (a malformed entry must
 * never beat the heuristic).
 */
export function resolveEtaWithSource(
  stageType: StageType | null | undefined,
  operation: GenerationActivityOperation | null | undefined,
  provider: AIProvider | null | undefined,
  liveEstimates: readonly GenerationEstimate[],
): ResolvedEta {
  const heuristic = estimateEta(stageType, operation)
  if (!provider || !stageType || liveEstimates.length === 0) {
    return { ...heuristic, source: "heuristic" }
  }
  const lookupOp = canonicalLookupOperation(operation)
  const hit = liveEstimates.find(
    (e) =>
      e.provider === provider &&
      e.stage === stageType &&
      e.operation === lookupOp,
  )
  if (
    hit &&
    Number.isFinite(hit.p50) &&
    Number.isFinite(hit.p90) &&
    hit.p50 > 0 &&
    hit.p90 >= hit.p50
  ) {
    return { p50: hit.p50, p90: hit.p90, source: "live" }
  }
  return { ...heuristic, source: "heuristic" }
}

/**
 * Backward-compatible band-only resolver (drops provenance). Retained for callers
 * that only need `{ p50, p90 }`; new code that gates on data source should use
 * `resolveEtaWithSource`.
 */
export function resolveEta(
  stageType: StageType | null | undefined,
  operation: GenerationActivityOperation | null | undefined,
  provider: AIProvider | null | undefined,
  liveEstimates: readonly GenerationEstimate[],
): EtaEstimate {
  const { p50, p90 } = resolveEtaWithSource(
    stageType,
    operation,
    provider,
    liveEstimates,
  )
  return { p50, p90 }
}

/** The bar decelerates toward this cap and never reaches it — the real `done`
 *  removes the overlay, so the bar must never claim 100% on a heuristic alone. */
export const ETA_PROGRESS_CAP = 0.9

/** Fraction of the cap the bar reaches exactly at `p90`; the curve is calibrated
 *  so it is past its midpoint by `p50` and creeps asymptotically thereafter. */
const FILL_AT_P90 = 0.9

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/**
 * Decelerating, asymptotic progress fraction in `[0, ETA_PROGRESS_CAP)`.
 *
 * `f(t) = CAP · (1 − e^(−t / τ))`, with τ chosen so `f(p90) = CAP · FILL_AT_P90`.
 * Concave (always decelerating), strictly < `CAP` for every finite `t`, and → `CAP`
 * as `t → ∞`. This is the "honest" half of the design: the bar visibly slows and
 * never completes on estimate alone.
 */
export function etaProgressFraction(
  elapsedSeconds: number,
  estimate: EtaEstimate,
): number {
  const p90 = Math.max(1, estimate.p90)
  // τ from the anchor: 1 − e^(−p90/τ) = FILL_AT_P90  ⇒  τ = p90 / ln(1/(1−FILL_AT_P90)).
  const tau = p90 / Math.log(1 / (1 - FILL_AT_P90))
  const elapsed = Math.max(0, elapsedSeconds)
  const fraction = ETA_PROGRESS_CAP * (1 - Math.exp(-elapsed / tau))
  return clamp(fraction, 0, ETA_PROGRESS_CAP)
}

export type EtaBand = "typical" | "overdue" | "long"

/**
 * The absolute mark past which a generation is "taking a while" regardless of the
 * per-stage estimate — the reassurance copy shifts from "a little longer than
 * usual" to concrete "this can take a few minutes" here so it never reads as
 * sarcastic at the multi-minute tail (the watchdog allows up to 900s). Held below
 * the hard cap so the "long" copy has room to sit before an actual stall surfaces.
 */
export const LONG_BAND_SECONDS = 180

/**
 * Three honest bands, monotonic in elapsed time:
 * - `typical`  — under the slow-tail `p90` mark; no time language at all.
 * - `overdue`  — past `p90` but not yet "long"; "a little longer than usual".
 * - `long`     — past `LONG_BAND_SECONDS` (or `p90` if that is later); concrete
 *                multi-minute reassurance.
 */
export function etaBand(elapsedSeconds: number, estimate: EtaEstimate): EtaBand {
  const longThreshold = Math.max(LONG_BAND_SECONDS, estimate.p90)
  if (elapsedSeconds >= longThreshold) return "long"
  if (elapsedSeconds >= estimate.p90) return "overdue"
  return "typical"
}

function roundUpTo(value: number, step: number): number {
  return Math.ceil(value / step) * step
}

/**
 * Friendly upper-bound label for a *live* estimate — rounded up so we
 * overestimate and beat it, never a false-precise median. Sub-minute rounds up to
 * the nearest 15s ("~45s"); a minute or more rounds up to the whole minute
 * ("~2 min"). Deliberately has no lower anchor — the median is exactly the number
 * that trained users to distrust the old "~30s" caption.
 */
export function formatUpperBound(seconds: number): string {
  if (seconds < 60) return `~${roundUpTo(Math.max(1, seconds), 15)}s`
  return `~${Math.ceil(seconds / 60)} min`
}

/**
 * The only numeric time caption the overlay may show, and only on a `"live"`
 * estimate — an upper bound derived from the real p90. Returns `null` on the
 * heuristic guess table (i.e. today, all traffic) so no number is shown.
 */
export function upperBoundCaption(estimate: ResolvedEta): string | null {
  if (estimate.source !== "live") return null
  return `usually under ${formatUpperBound(estimate.p90)}`
}

/**
 * The ETA hook named in the plan. Returns the static `{ p50, p90 }` band; the
 * time-varying bar fill and band are derived in the component from the existing
 * per-second `elapsedSeconds` ticker via the pure helpers above (kept separate
 * so the math is unit-testable in isolation).
 *
 * Phase 2b: when `provider` is known it prefers the live, data-backed band for
 * `(provider, stage, operation)` and falls back to the constant heuristic table
 * on any miss. The live fetch is fired here (idempotent, deduped in the store)
 * and is non-blocking — the bar renders immediately on the heuristic and
 * silently upgrades if/when live data arrives. With no provider (or no live
 * data) the behaviour is byte-identical to the Phase-2a heuristic path.
 */
export function useEtaEstimate(
  stageType: StageType | null | undefined,
  operation: GenerationActivityOperation | null | undefined,
  provider?: AIProvider | null,
): ResolvedEta {
  const liveEstimates = useGenerationEstimatesStore((s) => s.estimates)
  const ensureLoaded = useGenerationEstimatesStore((s) => s.ensureLoaded)

  useEffect(() => {
    // Best-effort, deduped in the store. Gated on the same flag that renders the
    // branded overlay (the only consumer of live data) so a flag-off session
    // makes zero new network calls, and only worth fetching when a provider is
    // known (otherwise we can only ever use the heuristic anyway).
    if (featureFlags.brandedLoaders && provider) void ensureLoaded()
  }, [provider, ensureLoaded])

  return useMemo(
    () => resolveEtaWithSource(stageType, operation, provider, liveEstimates),
    [stageType, operation, provider, liveEstimates],
  )
}

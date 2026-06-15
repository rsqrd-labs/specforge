import { describe, expect, it } from "vitest"

import type { GenerationEstimate } from "../../services/api"
import {
  ETA_PROGRESS_CAP,
  canonicalLookupOperation,
  estimateEta,
  etaBand,
  etaProgressFraction,
  resolveEta,
  type EtaEstimate,
} from "./useEtaEstimate"

describe("estimateEta (baseline lookup)", () => {
  it("returns the per-stage baseline for a full generation", () => {
    expect(estimateEta("spec", "generate")).toEqual({ p50: 30, p90: 75 })
    expect(estimateEta("harness", "generate")).toEqual({ p50: 60, p90: 130 })
  })

  it("treats regenerate / quality-gate-regenerate as a full stage run", () => {
    expect(estimateEta("plan", "regenerate")).toEqual(estimateEta("plan", "generate"))
    expect(estimateEta("plan", "quality-gate-regenerate")).toEqual(
      estimateEta("plan", "generate"),
    )
  })

  it("scales a gap regenerate below a full generation of the same stage", () => {
    const full = estimateEta("harness", "generate")
    const gap = estimateEta("harness", "regenerate-gaps")
    expect(gap.p50).toBeLessThan(full.p50)
    expect(gap.p90).toBeLessThan(full.p90)
    expect(gap.p50).toBeGreaterThan(0)
  })

  it("uses a small, stage-independent estimate for a focused patch", () => {
    expect(estimateEta("spec", "focused-patch")).toEqual({ p50: 18, p90: 45 })
    expect(estimateEta("tasks", "focused-patch")).toEqual(
      estimateEta("spec", "focused-patch"),
    )
  })

  it("falls back to a sane default for unknown / missing input (never throws)", () => {
    const fallback = estimateEta(undefined, undefined)
    expect(fallback.p50).toBeGreaterThan(0)
    expect(fallback.p90).toBeGreaterThan(fallback.p50)
    // An unknown stage falls back rather than returning undefined.
    expect(estimateEta("mystery" as never, "generate")).toEqual(fallback)
  })
})

describe("etaProgressFraction (decelerating asymptote)", () => {
  const eta: EtaEstimate = { p50: 45, p90: 100 }

  it("starts at zero", () => {
    expect(etaProgressFraction(0, eta)).toBe(0)
  })

  it("never reaches 100% and never exceeds the cap, for any elapsed time", () => {
    // The honest invariant: the bar caps at ETA_PROGRESS_CAP and never claims
    // completion on estimate alone — only the real `done` removes the overlay.
    // (At very large t the exponential underflows to exactly the cap; that is
    // the cap, not 100%, so it remains honest.)
    for (const t of [1, 45, 100, 500, 5_000, 100_000]) {
      const fraction = etaProgressFraction(t, eta)
      expect(fraction).toBeLessThanOrEqual(ETA_PROGRESS_CAP)
      expect(fraction).toBeLessThan(1)
    }
  })

  it("stays strictly below the cap around the realistic time horizon", () => {
    // Within the watchdog's hard cap (~900s) the curve is still climbing — it
    // visibly decelerates rather than parking on the cap.
    expect(etaProgressFraction(900, eta)).toBeLessThan(ETA_PROGRESS_CAP)
  })

  it("monotonically increases and decelerates (concave)", () => {
    const f10 = etaProgressFraction(10, eta)
    const f20 = etaProgressFraction(20, eta)
    const f30 = etaProgressFraction(30, eta)
    expect(f20).toBeGreaterThan(f10)
    expect(f30).toBeGreaterThan(f20)
    // Each equal-width step adds less than the previous one — decelerating.
    expect(f30 - f20).toBeLessThan(f20 - f10)
  })

  it("approaches the cap as elapsed grows large", () => {
    expect(etaProgressFraction(1_000_000, eta)).toBeCloseTo(ETA_PROGRESS_CAP, 5)
  })

  it("reaches ~90% of the cap at p90 (the calibration anchor)", () => {
    expect(etaProgressFraction(eta.p90, eta)).toBeCloseTo(
      ETA_PROGRESS_CAP * 0.9,
      6,
    )
  })

  it("clamps a negative elapsed time to zero rather than going negative", () => {
    expect(etaProgressFraction(-5, eta)).toBe(0)
  })
})

describe("etaBand", () => {
  const eta: EtaEstimate = { p50: 45, p90: 100 }

  it("is 'typical' before p90", () => {
    expect(etaBand(0, eta)).toBe("typical")
    expect(etaBand(99, eta)).toBe("typical")
  })

  it("flips to 'overdue' at and beyond p90", () => {
    expect(etaBand(100, eta)).toBe("overdue")
    expect(etaBand(250, eta)).toBe("overdue")
  })
})

describe("canonicalLookupOperation (Phase 2b grouping)", () => {
  it("collapses every full (re)generation onto the 'generate' bucket", () => {
    expect(canonicalLookupOperation("generate")).toBe("generate")
    expect(canonicalLookupOperation("regenerate")).toBe("generate")
    expect(canonicalLookupOperation("quality-gate-regenerate")).toBe("generate")
    expect(canonicalLookupOperation(undefined)).toBe("generate")
  })

  it("keeps the two patch flows in their own buckets", () => {
    expect(canonicalLookupOperation("focused-patch")).toBe("focused-patch")
    expect(canonicalLookupOperation("regenerate-gaps")).toBe("regenerate-gaps")
  })
})

describe("resolveEta (live data preferred, heuristic fallback)", () => {
  const live: GenerationEstimate[] = [
    { provider: "anthropic", stage: "spec", operation: "generate", p50: 22, p90: 58, n: 300 },
    {
      provider: "anthropic",
      stage: "spec",
      operation: "focused-patch",
      p50: 9,
      p90: 24,
      n: 120,
    },
    { provider: "openai", stage: "plan", operation: "generate", p50: 40, p90: 88, n: 210 },
  ]

  it("returns the heuristic when no provider is supplied", () => {
    expect(resolveEta("spec", "generate", undefined, live)).toEqual(
      estimateEta("spec", "generate"),
    )
  })

  it("returns the heuristic when there is no live data", () => {
    expect(resolveEta("spec", "generate", "anthropic", [])).toEqual(
      estimateEta("spec", "generate"),
    )
  })

  it("prefers the live band for a matching (provider, stage, operation)", () => {
    expect(resolveEta("spec", "generate", "anthropic", live)).toEqual({ p50: 22, p90: 58 })
    expect(resolveEta("plan", "generate", "openai", live)).toEqual({ p50: 40, p90: 88 })
  })

  it("canonicalises the operation before the live lookup", () => {
    // `regenerate` / `quality-gate-regenerate` resolve to the 'generate' band.
    expect(resolveEta("spec", "regenerate", "anthropic", live)).toEqual({ p50: 22, p90: 58 })
    expect(
      resolveEta("spec", "quality-gate-regenerate", "anthropic", live),
    ).toEqual({ p50: 22, p90: 58 })
    // A focused patch resolves to its own live band, not the generate one.
    expect(resolveEta("spec", "focused-patch", "anthropic", live)).toEqual({ p50: 9, p90: 24 })
  })

  it("falls back to the heuristic on a miss (wrong provider / stage / op)", () => {
    // No google data at all.
    expect(resolveEta("spec", "generate", "google", live)).toEqual(
      estimateEta("spec", "generate"),
    )
    // anthropic has spec data but not harness.
    expect(resolveEta("harness", "generate", "anthropic", live)).toEqual(
      estimateEta("harness", "generate"),
    )
    // No live regenerate-gaps band → heuristic gap estimate.
    expect(resolveEta("spec", "regenerate-gaps", "anthropic", live)).toEqual(
      estimateEta("spec", "regenerate-gaps"),
    )
  })

  it("rejects a malformed live entry rather than letting it beat the heuristic", () => {
    const bad: GenerationEstimate[] = [
      { provider: "anthropic", stage: "spec", operation: "generate", p50: 0, p90: 50, n: 99 },
      { provider: "openai", stage: "plan", operation: "generate", p50: 90, p90: 40, n: 99 },
      {
        provider: "google",
        stage: "tasks",
        operation: "generate",
        p50: Number.NaN,
        p90: 30,
        n: 99,
      },
    ]
    expect(resolveEta("spec", "generate", "anthropic", bad)).toEqual(
      estimateEta("spec", "generate"),
    )
    expect(resolveEta("plan", "generate", "openai", bad)).toEqual(
      estimateEta("plan", "generate"),
    )
    expect(resolveEta("tasks", "generate", "google", bad)).toEqual(
      estimateEta("tasks", "generate"),
    )
  })
})

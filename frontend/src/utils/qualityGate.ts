import type { QualityGateFinding, Stage } from "../types/stage"

/** Plain-language labels for critic finding kinds. The raw kinds (e.g.
 *  "CoverageGap", "ADRIncomplete") read like internal jargon; users see a short
 *  human label instead. Unknown kinds fall back to a generic "Suggestion".
 *  (issue #34 — "recommendations are not intuitive".) */
const FINDING_KIND_LABELS: Record<string, string> = {
  CoverageGap: "Uncovered requirement",
  MissingSection: "Missing section",
  ShallowSection: "Needs more detail",
  BannedPhrase: "Placeholder text",
  DeprecatedAPI: "Outdated technology",
  ADRIncomplete: "Incomplete decision record",
  ProblemStatementCondensed: "Condensed problem statement",
}

export function findingKindLabel(kind: string | null | undefined): string {
  if (!kind) return "Suggestion"
  return FINDING_KIND_LABELS[kind] ?? "Suggestion"
}

/** Finding kinds that are purely informational — a notice about how the input was
 *  processed, not a defect in the artifact. Regenerating cannot "address" them, so
 *  the advisory panel suppresses its regenerate action when these are the *only*
 *  findings (Phase D, problem-statement compression notice). */
const INFORMATIONAL_FINDING_KINDS = new Set<string>(["ProblemStatementCondensed"])

export function isInformationalFinding(
  kind: string | null | undefined,
): boolean {
  return kind != null && INFORMATIONAL_FINDING_KINDS.has(kind)
}

/** The non-blocking critic suggestions attached to a delivered draft. Present
 *  only when the persisted gate is `advisory` (issue #34); the draft is fully
 *  finalisable, these are improvement hints, never a block. */
export function deriveAdvisoryFindings(
  stage: Stage | null | undefined,
): QualityGateFinding[] {
  if (stage?.quality_gate?.status !== "advisory") return []
  return stage.quality_gate.findings ?? []
}

/** Last-resort finalise-block copy when the backend recovery contract is absent
 *  (e.g. a stage persisted before issue #28 shipped). The backend's
 *  `recovery.message` is preferred wherever it exists. */
export function gateFallbackMessage(kind: string | null | undefined): string {
  // Every blocking kind is overridable since issue #34: the user can regenerate
  // for a fresh version or finalise this one as-is.
  if (kind === "incomplete_output") {
    return "Regenerate for a complete version, or finalise this one as-is"
  }
  if (kind === "technology_safety") {
    return "Regenerate for an up-to-date version, or finalise this one as-is"
  }
  return "Regenerate, or override to finalise this version as-is"
}

/** Short header-badge label marking a blocked stage so it never reads as an
 *  ordinary, finalisable draft (issue #28, Phase 2). Kind-aware: only an
 *  `incomplete_output` block is literally a *partial* document; the other kinds
 *  produced a complete draft that the gate flagged, so they read "Blocked
 *  draft". The actionable, kind-specific copy is the recovery message below. */
export function blockedDraftLabel(kind: string | null | undefined): string {
  return kind === "incomplete_output" ? "Blocked partial draft" : "Blocked draft"
}

export interface FinaliseGateBlock {
  /** Whether finalise must be blocked for this stage. */
  blocked: boolean
  /** The single authoritative reason to show, backend-derived where available. */
  message: string
  /** The persisted gate kind when blocked, else null. */
  kind: string | null
  /** Short header-badge label for the blocked state (kind-aware). */
  label: string
}

/** Derive the finalise-block decision from the ONE authoritative source: the
 *  persisted `Stage.quality_gate` (issue #28, Phase 1). It is populated the
 *  moment the gate fires (the `quality_gate_failed` stream rejection refetches
 *  the stage) and after every refresh, and — unlike the transient, dismissable
 *  SSE `qualityGateMap` — it cannot be dismissed away. Pure so both the
 *  GenerateBar disable and the `handleFinalise` precheck read identical copy. */
export function deriveFinaliseGateBlock(
  stage: Stage | null | undefined,
): FinaliseGateBlock {
  const gate =
    stage?.quality_gate?.status === "blocked" ? stage.quality_gate : null
  return {
    blocked: Boolean(gate),
    message: gate?.recovery?.message ?? gateFallbackMessage(gate?.kind),
    kind: gate?.kind ?? null,
    label: blockedDraftLabel(gate?.kind),
  }
}

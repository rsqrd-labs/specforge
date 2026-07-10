import { hasActionableFindings } from "../components/workspace/QualityBadge"
import type { EvalResult, QualityGateFinding, Stage } from "../types/stage"

/** Plain-language labels for quality-gate finding kinds. The raw kinds and
 *  technology-safety codes (e.g. "CoverageGap", "ADRIncomplete",
 *  "technology_eol", "vulnerable_dependency") read like internal jargon; users
 *  see a short human label instead. (issue #34 — "recommendations are not
 *  intuitive"; the blocking gate popup used to render these codes raw.) */
const FINDING_KIND_LABELS: Record<string, string> = {
  // Critic finding kinds (advisory + legacy blocking critic gate).
  CoverageGap: "Uncovered requirement",
  MissingSection: "Missing section",
  ShallowSection: "Needs more detail",
  BannedPhrase: "Placeholder text",
  DeprecatedAPI: "Outdated technology",
  ADRIncomplete: "Incomplete decision record",
  ProblemStatementCondensed: "Condensed problem statement",
  // Technology-safety codes (blocking gate; see backend tech_safety.py).
  technology_eol: "End-of-life technology",
  technology_near_eol: "Technology nearing end-of-life",
  support_status_blocked: "Unsupported technology",
  vulnerable_dependency: "Known security vulnerability",
  technology_unmaintained: "Unmaintained technology",
  hard_denylist_match: "Disallowed technology",
  technology_safety_unverified: "Could not verify technology",
  technology_policy_stale: "Safety policy needs review",
  technology_policy_unverified: "Safety policy needs review",
  // Incomplete-output reason code (blocking gate; see backend validator).
  provider_stopped_by_limit: "Output was cut off",
}

/** Map a finding/reason code to a plain-language label.
 *
 *  The `fallback` matters: the advisory panel defaults to "Suggestion" (its
 *  findings are optional), but the BLOCKING gate must pass a neutral fallback
 *  like "Issue" — calling an unmapped EOL/vulnerability block a "Suggestion"
 *  would tell the user a hard block is optional. Keep the kind map exhaustive
 *  for the blocking codes above so the fallback rarely fires there anyway. */
export function findingKindLabel(
  kind: string | null | undefined,
  fallback = "Suggestion",
): string {
  if (!kind) return fallback
  return FINDING_KIND_LABELS[kind] ?? fallback
}

/** Plain-language severity labels. Raw values ("critical", "unknown") render as
 *  lowercase jargon; "unknown" in particular reads as broken ("· unknown"), so
 *  it becomes "Could not verify". Returns null when there is nothing to show. */
const SEVERITY_LABELS: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  unknown: "Could not verify",
}

export function findingSeverityLabel(
  severity: string | null | undefined,
): string | null {
  if (!severity) return null
  return SEVERITY_LABELS[severity.toLowerCase()] ?? severity
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
 *  finalisable, these are improvement hints, never a block.
 *
 *  Suppressed once the stage is `finalised`: the user has accepted the artifact
 *  as-is, so the suggestions are moot and must not keep floating on screen. They
 *  return automatically if the stage is unlocked (status leaves `finalised`),
 *  since the persisted advisory gate is untouched. */
export function deriveAdvisoryFindings(
  stage: Stage | null | undefined,
): QualityGateFinding[] {
  if (!stage || stage.status === "finalised") return []
  if (stage.quality_gate?.status !== "advisory") return []
  return stage.quality_gate.findings ?? []
}

/** Reconcile the two independent judge signals when they visibly disagree
 *  (audit theme 1): the eval badge derives "Ready" from deterministic eval
 *  findings while the critic's advisory panel lists suggestions — shown side
 *  by side with no explanation, "Ready" next to "3 suggestions" reads as a
 *  contradiction. Returns a short note for the advisory panel explaining the
 *  split, or null when there is nothing to reconcile.
 *
 *  Only the one soundly-derivable direction is reported: critic suggestions
 *  present while the eval shows no actionable gaps. The converse (eval flags a
 *  gap, critic silent) is NOT derivable — a passing critic persists nothing,
 *  so "critic found nothing" is indistinguishable from "critic still running /
 *  sampled out / failed open", and claiming agreement or disagreement there
 *  would fabricate a signal. Pure and race-free: it derives from whatever both
 *  surfaces already render, in whichever order the two background judges land. */
export function deriveJudgeReconciliationNote(
  evalResult: EvalResult | null | undefined,
  findings: QualityGateFinding[],
): string | null {
  if (!evalResult) return null
  const actionable = findings.filter((f) => !isInformationalFinding(f.kind))
  if (actionable.length === 0) return null
  if (hasActionableFindings(evalResult)) return null
  const noun = actionable.length === 1 ? "suggestion" : "suggestions"
  return (
    "The automated quality check found no gaps in this version, while the " +
    `deeper review left ${actionable.length === 1 ? "this" : "these"} ${noun}. ` +
    "The two checks look at different things — read the " +
    `${noun} as targeted improvements, not a lower overall rating.`
  )
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

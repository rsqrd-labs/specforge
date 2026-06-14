import type { Stage } from "../types/stage"

/** Last-resort finalise-block copy when the backend recovery contract is absent
 *  (e.g. a stage persisted before issue #28 shipped). The backend's
 *  `recovery.message` is preferred wherever it exists. */
export function gateFallbackMessage(kind: string | null | undefined): string {
  if (kind === "incomplete_output") {
    return "Regenerate a complete version before finalising"
  }
  if (kind === "technology_safety") {
    return "Regenerate with supported technology choices before finalising"
  }
  return "Regenerate or override the quality gate before finalising"
}

export interface FinaliseGateBlock {
  /** Whether finalise must be blocked for this stage. */
  blocked: boolean
  /** The single authoritative reason to show, backend-derived where available. */
  message: string
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
  }
}

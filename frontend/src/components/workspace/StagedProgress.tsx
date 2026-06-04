/**
 * StagedProgress — the shared staged-async-progress checklist (Phase 21).
 *
 * One calm vocabulary for "something is happening on a worker" across the
 * GitHub surfaces: a vertical list of quiet slate stages where completed steps
 * settle with a small saffron tick and the current step pulses — never a bare
 * spinner, never a fake percentage. Used by the mode-aware export modal (T-288)
 * and the increment-creation flow (T-289).
 *
 * Purely presentational: the owner advances `stageIndex` (on a timer, a poll,
 * or an awaited request) and decides what "done" means. Steps at index <
 * stageIndex are done, == is active, > is pending.
 */

import { ShippedCheckIcon } from "../shared/icons"

interface StagedProgressProps {
  stages: string[]
  stageIndex: number
}

export function StagedProgress({ stages, stageIndex }: StagedProgressProps) {
  return (
    <ol className="gh-stage-list" aria-live="polite">
      {stages.map((label, i) => {
        const state =
          i < stageIndex ? "done" : i === stageIndex ? "active" : "pending"
        return (
          <li key={label} className={`gh-stage ${state}`}>
            <span className="gh-stage-tick" aria-hidden="true">
              {state === "done" ? (
                <ShippedCheckIcon />
              ) : (
                <span className="gh-stage-dot" />
              )}
            </span>
            <span className="gh-stage-label">
              {label}
              {state === "active" ? "…" : ""}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

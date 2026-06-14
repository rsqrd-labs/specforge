import type { Stage } from "../../types/stage"
import { deriveFinaliseGateBlock } from "../../utils/qualityGate"

/** Header badge marking a stage whose persisted quality gate is blocked, so a
 *  blocked/partial draft never reads as an ordinary, finalisable draft
 *  (issue #28, Phase 2). It derives entirely from the authoritative
 *  `Stage.quality_gate` via `deriveFinaliseGateBlock` — never the dismissable
 *  SSE `qualityGateMap` — so it persists through "Hide details" and survives a
 *  refresh with no map dependency to lose. */
export function BlockedPartialBadge({
  stage,
}: {
  stage: Stage | null | undefined
}) {
  const { blocked, label, message } = deriveFinaliseGateBlock(stage)
  if (!blocked) return null
  return (
    <span className="workspace-blocked-chip" title={message}>
      {label}
    </span>
  )
}

interface BlockedPartialNoticeProps {
  /** The backend-derived (or kind-fallback) recovery reason. */
  message: string
  /** Kind-aware badge label, matching the header badge. */
  label: string
  /** Re-open the collapsed findings panel. Reads from the persisted stage
   *  object, so it is offered only when there are findings to re-show. */
  onShowDetails?: () => void
}

/** The persistent, non-destructive replacement for a dismissed findings panel
 *  (issue #28, Phase 2). When the user collapses the panel with "Hide details",
 *  the blocked state must not vanish: this slim notice keeps the blocked label
 *  and the recovery reason on screen, with an optional "Show details" to
 *  re-expand. Like the badge, it is driven by the stage object, not the
 *  dismissable map. */
export function BlockedPartialNotice({
  message,
  label,
  onShowDetails,
}: BlockedPartialNoticeProps) {
  return (
    <div className="quality-gate-collapsed" role="status">
      <div className="quality-gate-collapsed-text">
        <span className="workspace-blocked-chip">{label}</span>
        <p className="quality-gate-collapsed-reason">{message}</p>
      </div>
      {onShowDetails ? (
        <button
          type="button"
          className="btn btn-ghost"
          onClick={onShowDetails}
        >
          Show details
        </button>
      ) : null}
    </div>
  )
}

import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import type { QualityGateFinding, StageType } from "../../types/stage"
import { findingKindLabel, isInformationalFinding } from "../../utils/qualityGate"

interface AdvisoryFindingsPanelProps {
  /** The non-blocking critic suggestions for the current draft. */
  findings: QualityGateFinding[]
  /** Stage these suggestions belong to, for the heading copy. */
  stageType: StageType
  /** Regenerate the stage to try to address the suggestions. */
  onRegenerate?: () => void
  /** Disable actions while a workspace-level mutation holds the lock. */
  actionsDisabled?: boolean
  /** Reason the actions are disabled (shown as a note + tooltip). */
  disabledReason?: string
}

/** Non-blocking "suggestions" surface for a delivered, finalisable draft whose
 *  LLM quality review left findings (issue #34). Rendered as a floating,
 *  body-portaled popup — the same `.quality-gate-popup` chrome the blocking gate
 *  uses (StreamingOverlay), in its amber `.advisory` tone — so it never reflows
 *  the workspace column or gets clipped by `<main>`'s `overflow: clip`, and reads
 *  coherently with the rest of the workspace. Unlike the blocking gate it never
 *  stops finalisation, uses `role="status"` (not `alertdialog`), and dismiss
 *  collapses it to a slim, re-openable chip rather than closing it outright.
 *  Reads from the persisted `Stage.quality_gate` (status="advisory"), so it
 *  survives refresh and is not tied to a transient stream event. */
export function AdvisoryFindingsPanel({
  findings,
  stageType,
  onRegenerate,
  actionsDisabled = false,
  disabledReason,
}: AdvisoryFindingsPanelProps) {
  // Default to the slim, re-openable pill rather than the full card. The advisory
  // is optional/non-blocking, and the dense workspace has no collision-free corner
  // for a 420px floating card (it landed on the coverage cards on the right and the
  // Finalise action row on the left). The pill covers next to nothing; the user
  // expands it on demand.
  const [collapsed, setCollapsed] = useState(true)

  // Esc collapses the floating popup, like any lightweight overlay. No focus
  // trap — it is non-blocking, so the user keeps reading and scrolling the
  // generated document behind it.
  useEffect(() => {
    if (findings.length === 0 || collapsed) return undefined
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCollapsed(true)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [findings.length, collapsed])

  if (findings.length === 0) return null

  const count = findings.length
  // Only offer "Regenerate to address" when at least one finding is an actual
  // artifact defect the critic can fix. A purely informational notice (e.g. the
  // problem statement was condensed to fit budget) cannot be regenerated away, so
  // the action would mislead (Phase D). The word used for the findings tracks this
  // too: "suggestion" implies an action; an info-only panel reads as "note".
  const actionable = findings.some((f) => !isInformationalFinding(f.kind))
  const noun = actionable ? "suggestion" : "note"
  const plural = count === 1 ? "" : "s"
  const disabledReasonId = disabledReason
    ? "advisory-findings-disabled-reason"
    : undefined

  if (collapsed) {
    // A slim, re-openable chip pinned bottom-left (it shares the popup anchor,
    // and the blocking gate is mutually exclusive with the advisory state, so
    // they never collide). This is the default state now, so the suggestions stay
    // reachable without the full card holding the viewport.
    return createPortal(
      <div className="quality-gate-reopen advisory" role="status">
        <span className="workspace-advisory-chip">
          {count} {noun}
          {plural}
        </span>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setCollapsed(false)}
        >
          Show {noun}s
        </button>
      </div>,
      document.body,
    )
  }

  // Floating, body-portaled popup (not an inline block): fixed to the viewport so
  // it never reflows the workspace column, never squeezes the document out of
  // view, and is never clipped by `<main>`'s `overflow: clip`. Dismiss (✕ / Esc /
  // "Dismiss") collapses it to the re-open chip.
  return createPortal(
    <div
      className="quality-gate-popup advisory"
      role="status"
      aria-label="Quality review suggestions"
    >
      <div className="quality-gate-panel">
        <button
          type="button"
          className="quality-gate-close"
          onClick={() => setCollapsed(true)}
          aria-label={`Dismiss ${noun}s`}
        >
          ✕
        </button>
        <h3 className="quality-gate-title">
          This {stageType} is ready — {count} {actionable ? "optional " : ""}
          {noun}
          {plural}
        </h3>
        <p className="quality-gate-subtitle">
          {actionable
            ? `You can finalise this ${stageType} now. These are improvements the quality review suggested — address them only if they matter to you.`
            : `You can finalise this ${stageType} now. These notes explain how it was generated — review them if they matter to you.`}
        </p>
        <ul className="quality-gate-findings">
          {findings.map((finding, index) => (
            <li key={index} className="quality-gate-finding">
              <span className="quality-gate-kind">
                {findingKindLabel(finding.kind)}
              </span>
              {finding.reference ? (
                <span className="quality-gate-ref"> · {finding.reference}</span>
              ) : null}
              <span className="quality-gate-detail"> — {finding.detail}</span>
            </li>
          ))}
        </ul>
        <div className="quality-gate-actions">
          {actionsDisabled && disabledReason ? (
            <p id={disabledReasonId} className="workspace-lock-inline-note">
              {disabledReason}
            </p>
          ) : null}
          {onRegenerate && actionable ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onRegenerate}
              disabled={actionsDisabled}
              title={actionsDisabled ? disabledReason : undefined}
              aria-describedby={actionsDisabled ? disabledReasonId : undefined}
            >
              Regenerate to address
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setCollapsed(true)}
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

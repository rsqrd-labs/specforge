import { useEffect, useState } from "react"
import { featureFlags } from "../../config/featureFlags"
import type { GenerationProgress } from "../../services/sseService"
import type { QualityGateInfo, StageType } from "../../types/stage"
import { BrandLoader } from "../shared/BrandLoader"

export type GenerationActivityOperation =
  | "generate"
  | "regenerate"
  | "regenerate-gaps"
  | "focused-patch"
  | "quality-gate-regenerate"

export interface GenerationActivityInfo {
  stageId: string
  stageType: StageType
  operation: GenerationActivityOperation
  actionLabel: string
  startedAt: number
  streamed: boolean
}

interface StreamingOverlayProps {
  isVisible: boolean
  activity?: GenerationActivityInfo | null
  /** Latest backend liveness heartbeat, emitted every ~10s while the
   *  generation pipeline works without visible tokens (frontier-model
   *  reasoning, quality gates).  Confirms the connection is alive so a long
   *  generation never looks like a frozen loading screen — issue #19. */
  progress?: GenerationProgress | null
  /** Progressive streaming: live draft tokens are rendering in the editor
   *  behind this overlay — collapse to a slim status pill so the user can
   *  watch the document grow. */
  compact?: boolean
  /** Critic quality-gate findings, present when a generation was held back
   *  by the gate (T-247).  Rendered as an interactive panel with regenerate
   *  and owner-only override actions. */
  gate?: QualityGateInfo
  /** Re-run generation for the stage, replacing the blocked draft. */
  onRegenerate?: () => void
  /** Accept the current blocked draft without disabling the workspace critic. */
  onOverride?: () => void
  /** Dismiss the findings panel without acting. */
  onDismiss?: () => void
  actionsDisabled?: boolean
  disabledReason?: string
}

export function StreamingOverlay({
  isVisible,
  activity,
  progress,
  compact = false,
  gate,
  onRegenerate,
  onOverride,
  onDismiss,
  actionsDisabled = false,
  disabledReason,
}: StreamingOverlayProps) {
  const [renderedActivity, setRenderedActivity] =
    useState<GenerationActivityInfo | null>(activity ?? null)
  const [isExiting, setIsExiting] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  // Local elapsed ticker from the activity start, so the overlay visibly
  // progresses every second even between backend heartbeats.
  useEffect(() => {
    if (!activity || !isVisible) {
      setElapsedSeconds(0)
      return undefined
    }
    const tick = () =>
      setElapsedSeconds(Math.floor((Date.now() - activity.startedAt) / 1000))
    tick()
    const intervalId = window.setInterval(tick, 1000)
    return () => window.clearInterval(intervalId)
  }, [activity, isVisible])

  useEffect(() => {
    if (activity && isVisible) {
      setRenderedActivity(activity)
      setIsExiting(false)
      return undefined
    }

    if (!renderedActivity) {
      return undefined
    }

    setIsExiting(true)
    const timeoutId = window.setTimeout(() => {
      setRenderedActivity(null)
      setIsExiting(false)
    }, 220)

    return () => window.clearTimeout(timeoutId)
  }, [activity, isVisible, renderedActivity])

  if (gate) {
    const missing = gate.missing ?? []
    const findings = gate.findings ?? []
    const reasons = gate.reasons ?? []
    const isIncomplete = gate.kind === "incomplete_output"
    const isTechnologySafety = gate.kind === "technology_safety"
    const isMissingSections = gate.kind === "missing_sections" || missing.length > 0
    const structuredIssues = reasons.length ? reasons : findings
    const issueCount = isIncomplete || isTechnologySafety
      ? reasons.length || findings.length
      : isMissingSections
        ? missing.length
        : findings.length
    const canOverride = gate.override_allowed !== false && !isIncomplete && !isTechnologySafety
    // Recovery CTA (issue #28, Phase 3): for the non-overridable kinds, retry IS
    // the recovery, so the primary action reads as an explicit, non-punitive
    // "Retry generation" rather than the neutral "Regenerate". Overridable kinds
    // keep "Regenerate" alongside "Override and continue".
    const isNonOverridable = isIncomplete || isTechnologySafety
    const regenerateLabel = isNonOverridable ? "Retry generation" : "Regenerate"
    // Billing-honest sub-copy, driven solely by the backend's refund truth — the
    // generation-time block refunds the failed attempt; the finalise-time
    // re-check reports `false`. Single source of truth, no per-kind guessing.
    const showRefundNote = Boolean(gate.recovery?.refunded_prior_attempt)
    const disabledReasonId = disabledReason ? "quality-gate-disabled-reason" : undefined
    return (
      <div
        className="quality-gate-inline"
        role="alertdialog"
        aria-label="Quality gate findings"
      >
        <div className="quality-gate-panel">
          <h3 className="quality-gate-title">Quality gate held this generation back</h3>
          <p className="quality-gate-subtitle">
            {isIncomplete
              ? `The generated ${gate.stage} stopped before completion${
                  gate.repair_attempted ? " after a repair attempt" : ""
                }. Regenerate to produce a complete version.`
              : isTechnologySafety
              ? `The generated ${gate.stage} selected unsafe or unsupported technology${
                  issueCount === 1 ? "" : " choices"
                }${
                  gate.repair_attempted ? " after a repair attempt" : ""
                }. Regenerate with supported choices.`
              : isMissingSections
              ? `The generated ${gate.stage} is missing ${issueCount} required ${
                  issueCount === 1 ? "section" : "sections"
                }. Regenerate to try again, or override to accept anyway.`
              : `The critic found ${issueCount} ${
                  issueCount === 1 ? "issue" : "issues"
                } in the generated ${gate.stage}. Regenerate to try again, or override to accept anyway.`}
          </p>
          {isIncomplete || isTechnologySafety ? (
            <ul className="quality-gate-findings">
              {structuredIssues.map((reason, index) => (
                <li key={index} className="quality-gate-finding">
                  <span className="quality-gate-kind">
                    {reason.code ?? reason.kind}
                  </span>
                  {"severity" in reason && reason.severity ? (
                    <span className="quality-gate-ref"> · {reason.severity}</span>
                  ) : null}
                  {reason.reference ? (
                    <span className="quality-gate-ref"> · {reason.reference}</span>
                  ) : null}
                  <span className="quality-gate-detail"> — {reason.detail}</span>
                  {"remediation" in reason && reason.remediation ? (
                    <span className="quality-gate-detail"> {reason.remediation}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : isMissingSections ? (
            <ul className="quality-gate-findings">
              {missing.map((heading) => (
                <li key={heading} className="quality-gate-finding">
                  <span className="quality-gate-kind">MissingSection</span>
                  <span className="quality-gate-detail"> — {heading}</span>
                </li>
              ))}
            </ul>
          ) : (
            <ul className="quality-gate-findings">
              {findings.map((finding, index) => (
                <li key={index} className="quality-gate-finding">
                  <span className="quality-gate-kind">{finding.kind}</span>
                  {finding.reference ? (
                    <span className="quality-gate-ref"> · {finding.reference}</span>
                  ) : null}
                  <span className="quality-gate-detail"> — {finding.detail}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="quality-gate-actions">
            {actionsDisabled && disabledReason ? (
              <p id={disabledReasonId} className="workspace-lock-inline-note">
                {disabledReason}
              </p>
            ) : null}
            {showRefundNote ? (
              <p className="quality-gate-refund-note" role="note">
                Your previous attempt was refunded.
              </p>
            ) : null}
            {onRegenerate ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={onRegenerate}
                disabled={actionsDisabled}
                title={actionsDisabled ? disabledReason : undefined}
                aria-describedby={actionsDisabled ? disabledReasonId : undefined}
              >
                {regenerateLabel}
              </button>
            ) : null}
            {onOverride && canOverride ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onOverride}
                disabled={actionsDisabled}
                title={actionsDisabled ? disabledReason : undefined}
                aria-describedby={actionsDisabled ? disabledReasonId : undefined}
              >
                Override and continue
              </button>
            ) : null}
            {onDismiss ? (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={onDismiss}
                disabled={actionsDisabled}
                title={actionsDisabled ? disabledReason : undefined}
                aria-describedby={actionsDisabled ? disabledReasonId : undefined}
              >
                Hide details
              </button>
            ) : null}
          </div>
        </div>
      </div>
    )
  }

  if (!renderedActivity) return null

  if (compact && isVisible) {
    const compactCopy = getActivityCopy(renderedActivity)
    return (
      <div
        className="generation-streaming-pill"
        role="status"
        aria-live="polite"
        aria-busy="true"
        aria-label={`${compactCopy.title} for ${compactCopy.stageLabel}`}
      >
        <span className="generation-pill-dot" aria-hidden="true" />
        <span>
          {compactCopy.stageLabel}: {compactCopy.title} —{" "}
          {formatElapsed(elapsedSeconds)}
        </span>
      </div>
    )
  }

  const copy = getActivityCopy(renderedActivity)
  const activeStageIndex = STAGE_FLOW.findIndex(
    (stage) => stage.type === renderedActivity.stageType,
  )
  const variant =
    renderedActivity.operation === "focused-patch"
      ? "patch"
      : renderedActivity.operation === "quality-gate-regenerate"
        ? "gate"
        : "stream"

  return (
    <div
      className={`streaming-overlay generation-loading-overlay ${isExiting ? "is-exiting" : ""}`}
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={`${copy.title} for ${copy.stageLabel}`}
    >
      <div className={`generation-loading-card ${variant}`}>
        <div className="generation-flow" aria-hidden="true">
          <div className="generation-flow-rail">
            {STAGE_FLOW.map((stage, index) => (
              <span
                key={stage.type}
                className={`generation-flow-node ${
                  index === activeStageIndex ? "active" : ""
                } ${index < activeStageIndex ? "complete" : ""}`}
              >
                {stage.label}
              </span>
            ))}
          </div>
          <div className="generation-trace-lane">
            <span className="generation-trace" />
          </div>
        </div>

        {featureFlags.brandedLoaders ? (
          // The overlay already owns the live region (role="status" above), so
          // the branded mark is embedded with the decorative `overlay` variant.
          // The stage rail and copy are preserved.
          <BrandLoader variant="overlay" size="lg" />
        ) : (
          <div className="generation-activity-visual" aria-hidden="true">
            {variant === "patch" ? (
              <div className="generation-patch-flow">
                <span className="patch-source-line wide" />
                <span className="patch-source-line" />
                <span className="patch-connector" />
                <span className="patch-result-line wide" />
                <span className="patch-result-line" />
              </div>
            ) : (
              <div className="generation-document-shimmer">
                <span className="doc-line wide" />
                <span className="doc-line" />
                <span className="doc-line short" />
                <span className="doc-line wide" />
              </div>
            )}
            {variant === "gate" ? <span className="generation-gate-check" /> : null}
          </div>
        )}

        <div className="generation-loading-copy">
          <span className="generation-loading-kicker">{copy.stageLabel}</span>
          <strong>{copy.title}</strong>
          <p>{copy.detail}</p>
          <p className="generation-loading-liveness">
            {formatElapsed(elapsedSeconds)} elapsed
            {progress
              ? " — the model is working; this can take several minutes."
              : elapsedSeconds >= 15
                ? " — frontier models can reason for a while before text appears."
                : ""}
          </p>
        </div>
      </div>
    </div>
  )
}

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`
}

const STAGE_FLOW: Array<{ type: StageType; label: string }> = [
  { type: "spec", label: "SPEC" },
  { type: "plan", label: "PLAN" },
  { type: "harness", label: "HARNESS" },
  { type: "tasks", label: "TASKS" },
]

const STAGE_ACTIVITY_COPY: Record<StageType, string> = {
  spec: "Structuring requirements",
  plan: "Designing architecture",
  harness: "Building validation harness",
  tasks: "Drafting implementation plan",
}

function getActivityCopy(activity: GenerationActivityInfo) {
  const stageLabel =
    STAGE_FLOW.find((stage) => stage.type === activity.stageType)?.label ?? "STAGE"

  if (activity.operation === "focused-patch") {
    return {
      stageLabel,
      title: "Preparing refinement",
      detail: "Reviewing the selected text and shaping a precise edit.",
    }
  }

  if (activity.operation === "quality-gate-regenerate") {
    return {
      stageLabel,
      title: "Regenerating with gate feedback",
      detail: "Applying the flagged findings before the next quality pass.",
    }
  }

  if (activity.operation === "regenerate-gaps") {
    return {
      stageLabel,
      title: "Regenerating coverage gaps",
      detail: "Repairing the missing coverage while preserving the current stage.",
    }
  }

  if (activity.operation === "regenerate") {
    return {
      stageLabel,
      title: "Regenerating stage",
      detail: STAGE_ACTIVITY_COPY[activity.stageType],
    }
  }

  return {
    stageLabel,
    title: STAGE_ACTIVITY_COPY[activity.stageType],
    detail: "Keeping the workspace responsive while the artifact is generated.",
  }
}

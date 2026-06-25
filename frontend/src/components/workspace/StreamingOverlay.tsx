import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { featureFlags } from "../../config/featureFlags"
import type { GenerationProgress } from "../../services/sseService"
import type { QualityGateInfo, StageType } from "../../types/stage"
import type { AIProvider } from "../../types/workspace"
import { findingKindLabel, findingSeverityLabel } from "../../utils/qualityGate"
import { BrandLoader } from "../shared/BrandLoader"
import {
  type EtaEstimate,
  etaBand,
  etaProgressFraction,
  useEtaEstimate,
} from "./useEtaEstimate"

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
  /** Workspace LLM provider, used to pick the live, data-backed ETA band for
   *  this provider (issue #21 Phase 2b). Optional — without it the ETA falls
   *  back to the provider-agnostic heuristic table. */
  provider?: AIProvider
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

  // Phase 2a heuristic ETA (issue #21). Called unconditionally (hooks rule) and
  // before any early return; the value is only consumed in the full-overlay path
  // below. Pure constant-table lookup — no backend dependency.
  const eta = useEtaEstimate(
    renderedActivity?.stageType,
    renderedActivity?.operation,
    renderedActivity?.provider,
  )

  // The findings popup is a non-blocking floating card — Esc dismisses it like
  // any lightweight overlay, but we deliberately do NOT focus-trap, so the user
  // keeps reading and scrolling the generated document behind it.
  useEffect(() => {
    if (!gate || !onDismiss || actionsDisabled) return undefined
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDismiss()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [gate, onDismiss, actionsDisabled])

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
    // Issue #34: every blocking kind is overridable now — the user owns the
    // artifact and may finalise it as-is — so override is offered for all kinds
    // (the backend's override_quality_gate accepts them all).
    const canOverride = gate.override_allowed !== false
    const regenerateLabel = "Regenerate"
    // Billing-honest sub-copy, driven solely by the backend's refund truth — the
    // generation-time block refunds the failed attempt; the finalise-time
    // re-check reports `false`. Single source of truth, no per-kind guessing.
    const showRefundNote = Boolean(gate.recovery?.refunded_prior_attempt)
    const disabledReasonId = disabledReason ? "quality-gate-disabled-reason" : undefined
    // Floating, body-portaled popup (not an inline block): fixed to the viewport
    // so it never reflows the workspace column or hides the generated document
    // behind it. The user can dismiss (✕ / Esc), regenerate, or override in place.
    return createPortal(
      <div
        className="quality-gate-popup"
        role="alertdialog"
        aria-label="Quality gate findings"
      >
        <div className="quality-gate-panel">
          {onDismiss ? (
            <button
              type="button"
              className="quality-gate-close"
              onClick={onDismiss}
              disabled={actionsDisabled}
              title={actionsDisabled ? disabledReason : undefined}
              aria-label="Dismiss findings"
            >
              ✕
            </button>
          ) : null}
          <h3 className="quality-gate-title">Quality gate held this generation back</h3>
          <p className="quality-gate-subtitle">
            {isIncomplete
              ? `The generated ${gate.stage} stopped before completion${
                  gate.repair_attempted ? " after a repair attempt" : ""
                }. Regenerate for a complete version, or override to finalise this one as-is.`
              : isTechnologySafety
              ? `The generated ${gate.stage} selected outdated or unsupported technology${
                  issueCount === 1 ? "" : " choices"
                }${
                  gate.repair_attempted ? " after a repair attempt" : ""
                }. Regenerate for an up-to-date version, or override to finalise this one as-is.`
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
                    {findingKindLabel(reason.code ?? reason.kind, "Issue")}
                  </span>
                  {"severity" in reason && reason.severity ? (
                    <span className="quality-gate-ref">
                      {" · "}
                      {findingSeverityLabel(reason.severity)}
                    </span>
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
                  <span className="quality-gate-kind">
                    {findingKindLabel("MissingSection")}
                  </span>
                  <span className="quality-gate-detail"> — {heading}</span>
                </li>
              ))}
            </ul>
          ) : (
            <ul className="quality-gate-findings">
              {findings.map((finding, index) => (
                <li key={index} className="quality-gate-finding">
                  <span className="quality-gate-kind">
                    {findingKindLabel(finding.kind, "Issue")}
                  </span>
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
      </div>,
      document.body,
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
  // Issue #21 Phase 2c: when the backend heartbeat reports a real pipeline phase
  // and the branded-loaders rollout is on, the liveness line names that phase
  // instead of the generic "still working" copy. Gated on the flag so a
  // flag-off session is byte-identical, and any unknown/missing phase falls back
  // to the generic copy — the field is additive and must never break the line.
  const phaseLiveness =
    featureFlags.brandedLoaders && progress?.phase
      ? phaseLivenessCopy(progress.phase)
      : null
  // Issue #39 UX: the parallel chunked path streams no visible tokens, so the
  // backend reports honest, monotonic part progress on the heartbeat. Show it
  // only while parts are actually being generated (the `streaming`/`refining`
  // phases) — once all parts are drafted the pipeline moves to the gate/critic
  // phases, where a stale "N of N parts" would mislead. Independent of the
  // branded-loaders flag: this is the core liveness signal, not decoration.
  const totalParts = progress?.total_parts ?? 0
  const showParts =
    totalParts > 0 &&
    (progress?.phase === "streaming" || progress?.phase === "refining")
  const completedParts = Math.min(progress?.completed_parts ?? 0, totalParts)
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
              ? ` — ${phaseLiveness ?? "the model is working; this can take several minutes."}`
              : elapsedSeconds >= 15
                ? " — frontier models can reason for a while before text appears."
                : ""}
          </p>
          {showParts ? (
            <p className="generation-loading-parts" aria-live="polite">
              {completedParts} of {totalParts} parts drafted
            </p>
          ) : null}
          {/* Not during the exit fade: the elapsed ticker resets to 0 the moment
              the activity clears, so rendering the bar here would animate the
              fill backward toward empty as the card fades (a "progress goes
              backward" smell). The bar simply leaves with the card instead. */}
          {featureFlags.brandedLoaders && !isExiting ? (
            <EtaProgress elapsedSeconds={elapsedSeconds} eta={eta} />
          ) : null}
        </div>
      </div>
    </div>
  )
}

/**
 * Phase 2a honest ETA (issue #21). A decelerating bar that asymptotes near 90%
 * (`ETA_PROGRESS_CAP`) and a banded caption — never a countdown that hits zero
 * and keeps spinning. The bar is purely decorative (`aria-hidden`): it is a
 * heuristic, so the honest, screen-reader-announced signal is the caption text
 * (static app copy) sitting inside the overlay's existing live region. The fill
 * animates with `transform: scaleX` (compositor-only — no layout) so hundreds of
 * concurrent loaders cost nothing.
 */
function EtaProgress({
  elapsedSeconds,
  eta,
}: {
  elapsedSeconds: number
  eta: EtaEstimate
}) {
  const fraction = etaProgressFraction(elapsedSeconds, eta)
  const band = etaBand(elapsedSeconds, eta)
  const caption =
    band === "overdue"
      ? `usually ~${eta.p50}s · still working`
      : `usually ~${eta.p50}s`

  return (
    <div className="generation-eta">
      <span
        className={`generation-eta-bar generation-eta-bar--${band}`}
        aria-hidden="true"
      >
        <span
          className="generation-eta-fill"
          style={{ transform: `scaleX(${fraction})` }}
        />
      </span>
      <span className="generation-eta-caption">{caption}</span>
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

/**
 * Map a backend pipeline phase (issue #21 Phase 2c) to a short, honest liveness
 * sentence. Pure and total: an unknown or future phase returns `null` so the
 * caller falls back to the generic "still working" copy — the wire field is
 * additive and must never be the thing that breaks the loading screen. The
 * strings are static app copy and never echo model/user content.
 */
export function phaseLivenessCopy(phase: string): string | null {
  switch (phase) {
    case "streaming":
      return "the model is drafting; this can take several minutes."
    case "refining":
      return "refining the draft to fill remaining gaps."
    case "quality_gate":
      return "checking the draft against the quality gates."
    case "critic":
      return "a reviewer model is checking the draft for quality."
    case "persisting":
      return "finalising and saving the result."
    default:
      return null
  }
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

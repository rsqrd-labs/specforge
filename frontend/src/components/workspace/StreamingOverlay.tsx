import { type CSSProperties, useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { featureFlags } from "../../config/featureFlags"
import type { GenerationProgress } from "../../services/sseService"
import type { QualityGateInfo, StageType } from "../../types/stage"
import type { AIProvider } from "../../types/workspace"
import { findingKindLabel, findingSeverityLabel } from "../../utils/qualityGate"
import { BrandLoader } from "../shared/BrandLoader"
import { type EtaBand, etaBand, upperBoundCaption, useEtaEstimate } from "./useEtaEstimate"

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
  // Advance-only pipeline step index, driven by the real backend phase heartbeat.
  const [stepIndex, setStepIndex] = useState(0)
  // The set of pipeline steps we have *actually observed* on a heartbeat. Drafting
  // (0) is seeded because a generation always drafts. This lets the ring tell a
  // step that genuinely ran (→ complete) apart from one the pipeline jumped over
  // (→ skipped): in the default async-advisory path the phase hops
  // `quality_gate`(2) → `persisting`(4), so Reviewer (3) is never seen and must
  // not render a checkmark for work that ran detached (issue #34 honesty).
  const [seenSteps, setSeenSteps] = useState<Set<number>>(() => new Set([0]))

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

  // Reset the phase stepper when a new generation starts (stage or operation
  // changes), so a fresh run begins at Drafting rather than a stale later step.
  useEffect(() => {
    setStepIndex(0)
    setSeenSteps(new Set([0]))
  }, [activity?.stageId, activity?.operation])

  // Map the backend phase heartbeat to a pipeline step. Advance-only: an unknown
  // or absent phase (`phaseStepIndex` → 0) holds the last known step so the
  // stepper never visibly regresses mid-run. A step is recorded as *seen* only
  // when its phase actually arrives on a heartbeat, so a jumped-over step stays
  // out of `seenSteps` and renders skipped rather than complete.
  useEffect(() => {
    const next = phaseStepIndex(progress?.phase)
    setStepIndex((prev) => (next > prev ? next : prev))
    if (progress?.phase != null) {
      setSeenSteps((prev) =>
        prev.has(next) ? prev : new Set(prev).add(next),
      )
    }
  }, [progress?.phase])

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
  // Issue #39 UX: the parallel chunked path streams only its lead chunk per
  // wave live, so its silent sibling chunks show no text — the backend reports
  // honest, monotonic part progress on the heartbeat to cover the whole set.
  // Show it only while parts are actually being generated (the
  // `streaming`/`refining` phases) — once all parts are drafted the pipeline
  // moves to the gate/critic phases, where a stale "N of N parts" would mislead.
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

  // Legacy per-surface overlay, rendered only when a session has explicitly
  // opted out of branded loaders (`VITE_BRANDED_LOADERS=false`). Kept
  // byte-identical to the pre-issue-#48 markup so the opt-out path never
  // regresses; all the honest-time work below lives on the branded path.
  if (!featureFlags.brandedLoaders) {
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
            {showParts ? (
              <p className="generation-loading-parts" aria-live="polite">
                {completedParts} of {totalParts} parts drafted
              </p>
            ) : null}
          </div>
        </div>
      </div>
    )
  }

  // Branded, honest-time overlay (issue #48). The card is `aria-hidden` and the
  // single live region below announces only *milestone* changes (step / band),
  // never the per-second elapsed tick — one calm announcement, not a stream.
  const band = etaBand(elapsedSeconds, eta)
  const reassurance = bandReassurance(band)
  // The only numeric time caption we may show, and only on a live, data-backed
  // estimate (never the guess table). `null` today ⇒ no number rendered.
  const upperBound = upperBoundCaption(eta)
  // A focused patch edits a selection, not the whole artifact — it does not run
  // the five-stage pipeline, so it gets a calm indeterminate cue instead of the
  // phase ring, whose segments would sit permanently inert.
  const isPipeline = variant !== "patch"
  const partsLabel = showParts ? `${completedParts} of ${totalParts} parts` : null
  // The single status line that collapses the old vertical stepper + elapsed
  // footer into one row under the title. Verb phrasing ("step N of 5") is the
  // deliberate counterpoint to the noun stage rail ("SPEC/PLAN/…"), so the two
  // progress scales never read as the same 4-vs-5 sequence.
  const currentStep = PIPELINE_STEPS[stepIndex] ?? PIPELINE_STEPS[0]
  const phaseLine = `${currentStep.label} — step ${stepIndex + 1} of ${
    PIPELINE_STEPS.length
  } · ${formatElapsed(elapsedSeconds)}${partsLabel ? ` · ${partsLabel}` : ""}`

  return (
    <div
      className={`streaming-overlay generation-loading-overlay ${isExiting ? "is-exiting" : ""}`}
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={`${copy.title} for ${copy.stageLabel}`}
    >
      {/* Single, milestone-only announcement for assistive tech. The visual card
          is `aria-hidden`, so its per-second elapsed updates never reach the
          screen reader; only this string (changing on step / band) is spoken. */}
      <p className="sr-only">{liveMilestone(band, stepIndex)}</p>

      <div className={`generation-loading-card ${variant}`} aria-hidden="true">
        {/* Slim macro rail: which of the four stages this is. Deliberately quiet
            so it reads as orientation, distinct from the phase line below. */}
        <div className="generation-stage-rail">
          {STAGE_FLOW.map((stage, index) => (
            <span
              key={stage.type}
              className={`generation-stage-node ${
                index === activeStageIndex ? "active" : ""
              } ${index < activeStageIndex ? "complete" : ""}`}
            >
              {stage.label}
            </span>
          ))}
        </div>

        {/* The round shape is now the instrument: the brand mark sits inside a
            5-arc progress ring driven by the real phase heartbeat. On a focused
            patch (no pipeline) the mark stays a calm, unchromed loader. */}
        {isPipeline ? (
          <PhaseRing activeIndex={stepIndex} seenSteps={seenSteps} />
        ) : (
          <BrandLoader variant="overlay" size="lg" />
        )}

        <div className="generation-loading-copy">
          <strong>{copy.title}</strong>
          <p>{copy.detail}</p>
          {isPipeline ? (
            <p className="generation-phase-line">{phaseLine}</p>
          ) : null}
        </div>

        {isPipeline ? null : (
          <div className="generation-patch-activity">
            <span className="generation-patch-activity-fill" />
          </div>
        )}

        <div className={`generation-loading-status is-${band}`}>
          {isPipeline ? null : (
            <span className="generation-elapsed">
              {formatElapsed(elapsedSeconds)} elapsed
            </span>
          )}
          {reassurance ? (
            <span className="generation-reassurance">{reassurance}</span>
          ) : upperBound ? (
            <span className="generation-eta-bound">{upperBound}</span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/** The five pipeline steps the branded overlay narrates, in order. `announce`
 *  is the assistive-tech sentence for the milestone live region. */
interface PipelineStep {
  key: string
  label: string
  announce: string
}

const PIPELINE_STEPS: PipelineStep[] = [
  { key: "drafting", label: "Drafting", announce: "Drafting the document." },
  { key: "refining", label: "Refining", announce: "Refining the draft." },
  {
    key: "quality",
    label: "Quality checks",
    announce: "Running quality checks.",
  },
  {
    key: "reviewer",
    label: "Reviewer",
    announce: "A reviewer model is checking the draft.",
  },
  { key: "saving", label: "Saving", announce: "Saving your work." },
]

/**
 * Map a backend pipeline phase to a `PIPELINE_STEPS` index. Total and pure: an
 * unknown or absent phase returns 0 (Drafting) so the advance-only reducer in
 * the component holds the last known step rather than regressing. `critic` maps
 * to the Reviewer step, which the default async path usually skips — steps only
 * ever advance, so a skipped step is not a regression.
 */
export function phaseStepIndex(phase?: string | null): number {
  switch (phase) {
    case "streaming":
      return 0
    case "refining":
      return 1
    case "quality_gate":
      return 2
    case "critic":
      return 3
    case "persisting":
      return 4
    default:
      return 0
  }
}

/** Elapsed-band reassurance copy. `null` in the typical band — below the slow
 *  tail we make no time claim at all, so nothing can contradict the stepper. */
function bandReassurance(band: EtaBand): string | null {
  switch (band) {
    case "long":
      return "Still generating — detailed specs can take a few minutes. We'll flag it if it stalls."
    case "overdue":
      return "Taking a little longer than usual — still working."
    default:
      return null
  }
}

/** The single assistive-tech announcement. Once overdue, the band reassurance is
 *  the message; otherwise it names the current pipeline step. */
function liveMilestone(band: EtaBand, stepIndex: number): string {
  if (band === "long") {
    return "Still generating. This is taking longer than usual, but it is still working."
  }
  if (band === "overdue") {
    return "Still working. This is taking a little longer than usual."
  }
  return PIPELINE_STEPS[stepIndex]?.announce ?? PIPELINE_STEPS[0].announce
}

// Ring geometry (viewBox 0 0 100 100, centred). One arc per pipeline step. All
// derived so the segments tile the circle and the comet aligns to the active
// arc from the same formula.
const RING_RADIUS = 44
const RING_CIRC = 2 * Math.PI * RING_RADIUS
const RING_SEG_SPAN = RING_CIRC / PIPELINE_STEPS.length
const RING_GAP = RING_CIRC * 0.04
const RING_ARC_LEN = RING_SEG_SPAN - RING_GAP
const RING_COMET_LEN = RING_CIRC * 0.06

type RingSegmentState = "complete" | "active" | "skipped" | "upcoming"

/**
 * The visual state of ring segment `index`. A segment below the active one is
 * `complete` only if its phase was actually observed (`seen`); a step the
 * pipeline jumped over — Reviewer, in the default async-advisory path — is
 * `skipped` and never draws a filled arc, so the card never claims work that
 * did not run happened.
 */
function ringSegmentState(
  index: number,
  activeIndex: number,
  seen: Set<number>,
): RingSegmentState {
  if (index === activeIndex) return "active"
  if (index > activeIndex) return "upcoming"
  return seen.has(index) ? "complete" : "skipped"
}

/** Per-segment stroke-dashoffset that slots arc `index` into its position. */
function ringSegmentOffset(index: number): number {
  return -(index * RING_SEG_SPAN)
}

/**
 * The primary progress signal: a five-arc ring driven by the real backend phase
 * heartbeat, with the brand mark seated inside it. Purely visual (`aria-hidden`)
 * — the accessible equivalent is the milestone live region in the overlay.
 * Completed arcs fill, the active arc carries a comet that sweeps within its own
 * bounds (never a full-ring spin that would imply fake progress), skipped arcs
 * stay hollow, and upcoming arcs sit faint.
 */
function PhaseRing({
  activeIndex,
  seenSteps,
}: {
  activeIndex: number
  seenSteps: Set<number>
}) {
  const hasActive = activeIndex < PIPELINE_STEPS.length
  const cometFrom = ringSegmentOffset(activeIndex)
  const cometTo = cometFrom - (RING_ARC_LEN - RING_COMET_LEN)
  const cometStyle = {
    "--comet-from": `${cometFrom}`,
    "--comet-to": `${cometTo}`,
  } as CSSProperties

  return (
    <div className="generation-phase-ring" aria-hidden="true">
      <svg
        className="generation-phase-ring-svg"
        viewBox="0 0 100 100"
        focusable="false"
        role="presentation"
      >
        <g transform="rotate(-90 50 50)">
          {PIPELINE_STEPS.map((step, index) => (
            <circle
              key={step.key}
              className={`generation-ring-seg is-${ringSegmentState(
                index,
                activeIndex,
                seenSteps,
              )}`}
              cx="50"
              cy="50"
              r={RING_RADIUS}
              fill="none"
              strokeDasharray={`${RING_ARC_LEN} ${RING_CIRC - RING_ARC_LEN}`}
              strokeDashoffset={ringSegmentOffset(index)}
            />
          ))}
          {hasActive ? (
            <circle
              className="generation-ring-comet"
              cx="50"
              cy="50"
              r={RING_RADIUS}
              fill="none"
              strokeDasharray={`${RING_COMET_LEN} ${RING_CIRC - RING_COMET_LEN}`}
              strokeDashoffset={cometFrom}
              style={cometStyle}
            />
          ) : null}
        </g>
      </svg>
      <span className="generation-phase-ring-mark">
        <BrandLoader variant="overlay" size="lg" />
      </span>
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

const STAGE_ACTIVITY_DETAIL: Record<StageType, string> = {
  spec: "Turning your idea into functional requirements, constraints, and acceptance criteria.",
  plan: "Mapping components, data models, and the trade-offs behind each decision.",
  harness: "Defining the tests and contracts that will prove the build is correct.",
  tasks: "Sequencing the work into concrete, buildable engineering tasks.",
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
      detail:
        "Applying the reviewer's findings — this replaces the held draft with a corrected version.",
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
    detail: STAGE_ACTIVITY_DETAIL[activity.stageType],
  }
}

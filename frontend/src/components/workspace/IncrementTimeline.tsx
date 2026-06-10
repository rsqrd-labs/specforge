/**
 * IncrementTimeline — the "living workspace" spine (Phase 21, T-289).
 *
 * Moment-of-use feeling: opening a clean product changelog you're proud of — a
 * vertical spine of versions, each a small accomplishment, anchored by the v1
 * baseline at the bottom and growing upward. A calm compose box turns "I want
 * to add X" into the next increment; a quiet idea backlog (child) holds the
 * rest until you're ready.
 *
 * Layout sketch (a Tasks-stage side panel, sibling of TaskCompletionPanel):
 *   ┌ ws-panel-section ───────────────────────────────────┐
 *   │ INCREMENTS                                           │
 *   │ [ What do you want to add?                       Add ]│  ← compose
 *   │ ● Increment 2 · Ready                       Push     │  ← newest on top
 *   │ │                                                    │
 *   │ ✓ Increment 1 · Pushed                               │  ← node + rail
 *   │ │                                                    │
 *   │ ● v1 · Baseline                                      │  ← anchors bottom
 *   │ ── Ideas ─────────────────────────────────────────  │
 *   │ ✦ Dark mode          Promote                         │
 *   └──────────────────────────────────────────────────────┘
 *
 * Visual hierarchy: the saffron rail + nodes are the spine; titles lead, a quiet
 * slate meta line follows, status is a small bespoke glyph (never a pill grid).
 * The one delight: when an increment finishes pushing (its status flips to
 * `pushed` between polls), its node settles with a single gentle saffron pulse —
 * the timeline visibly "grew."
 *
 * Owns the increment + idea data, the synchronous credit-aware create (shown
 * with the shared StagedProgress vocabulary), the 202 push, and "promote" —
 * which *composes* (prefills the input) rather than mutating an idea, honest to
 * the backend (no update-idea endpoint; feature_request needs ≥ 8 chars).
 */

import { useCallback, useEffect, useRef, useState } from "react"

import {
  createIdea,
  createIncrement,
  getApiErrorMessage,
  listIdeas,
  listIncrements,
  pushIncrement,
} from "../../services/api"
import type { Increment, IncrementIdea } from "../../types/github"
import { ActionAlertPanel } from "../shared/ActionAlert"
import { DriftIcon, ShippedCheckIcon } from "../shared/icons"
import { IdeaBacklog } from "./IdeaBacklog"
import { StagedProgress } from "./StagedProgress"

const FEATURE_MIN = 8
const FEATURE_MAX = 4000

const CREATE_STAGES = [
  "Reading your baseline",
  "Planning the delta",
  "Writing the new tasks",
]
const CREATE_STAGE_ADVANCE_MS = 1800

// Gentle, visible-only poll so a worker-driven push (open→pushed) and ideas
// flowing back from GitHub appear without a manual refresh.
const POLL_INTERVAL_MS = 15_000

const STATUS_LABEL: Record<Increment["status"], string> = {
  draft: "Draft",
  generating: "Generating",
  ready: "Ready",
  pushed: "Pushed",
  stale: "Needs re-push",
}

interface IncrementTimelineProps {
  workspaceId: string
  enabled: boolean
  /** A live baseline push must exist for an increment push to be accepted —
   *  the backend 409s otherwise, so the action is hidden until then. */
  hasBaselinePush: boolean
  disabled?: boolean
  disabledReason?: string
}

function pushedSet(increments: Increment[]): Set<string> {
  return new Set(
    increments.filter((i) => i.status === "pushed").map((i) => i.id),
  )
}

export function IncrementTimeline({
  workspaceId,
  enabled,
  hasBaselinePush,
  disabled = false,
  disabledReason,
}: IncrementTimelineProps) {
  const [increments, setIncrements] = useState<Increment[]>([])
  const [ideas, setIdeas] = useState<IncrementIdea[]>([])
  const [loading, setLoading] = useState(true)

  const [feature, setFeature] = useState("")
  const [featureError, setFeatureError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [createStage, setCreateStage] = useState(0)
  const [createError, setCreateError] = useState<string | null>(null)

  const [capturing, setCapturing] = useState(false)
  const [pushingId, setPushingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [justPushed, setJustPushed] = useState<Set<string>>(new Set())

  const composeRef = useRef<HTMLTextAreaElement>(null)
  const mounted = useRef(true)
  const previouslyPushed = useRef<Set<string> | null>(null)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    const [incs, backlog] = await Promise.all([
      listIncrements(workspaceId).catch(() => [] as Increment[]),
      listIdeas(workspaceId).catch(() => [] as IncrementIdea[]),
    ])
    if (!mounted.current) return
    setIncrements(incs)
    setIdeas(backlog)
    setLoading(false)
  }, [workspaceId])

  useEffect(() => {
    if (!enabled) return undefined
    setLoading(true)
    void refresh()
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh()
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [enabled, refresh])

  // One-time saffron pulse when an increment newly flips to `pushed`. The ref is
  // seeded from the first fetch so already-pushed nodes never flash on mount.
  useEffect(() => {
    const current = pushedSet(increments)
    const previous = previouslyPushed.current
    previouslyPushed.current = current
    if (previous === null) return
    const newly = [...current].filter((id) => !previous.has(id))
    if (newly.length === 0) return
    setJustPushed(new Set(newly))
    const handle = window.setTimeout(() => setJustPushed(new Set()), 1600)
    return () => window.clearTimeout(handle)
  }, [increments])

  // Advance the staged-progress labels while a (synchronous) generate is in
  // flight — purely cosmetic; the resolved request is the source of truth.
  useEffect(() => {
    if (!creating) return undefined
    setCreateStage(0)
    const timer = window.setInterval(() => {
      setCreateStage((i) => Math.min(i + 1, CREATE_STAGES.length - 1))
    }, CREATE_STAGE_ADVANCE_MS)
    return () => window.clearInterval(timer)
  }, [creating])

  async function handleCreate() {
    if (disabled) return
    const text = feature.trim()
    if (text.length < FEATURE_MIN) {
      setFeatureError(
        "Describe the change in a little more detail (at least 8 characters).",
      )
      return
    }
    setFeatureError(null)
    setCreateError(null)
    setCreating(true)
    try {
      await createIncrement(workspaceId, {
        feature_request: text,
        mode: "additive",
      })
      if (!mounted.current) return
      setFeature("")
      await refresh()
    } catch (caught) {
      if (!mounted.current) return
      const status =
        typeof caught === "object" && caught !== null && "response" in caught
          ? (caught as { response?: { status?: number } }).response?.status
          : undefined
      setCreateError(
        status === 402
          ? "You're out of credits — top up to generate an increment."
          : status === 409
            ? "Finalise all four stages before adding an increment."
            : status === 422
              ? "That didn't produce any new tasks — try naming a concrete feature."
              : getApiErrorMessage(caught, "Couldn't generate the increment. Please try again."),
      )
    } finally {
      if (mounted.current) setCreating(false)
    }
  }

  async function handleCapture(text: string) {
    if (disabled) return
    setCapturing(true)
    setActionError(null)
    try {
      await createIdea(workspaceId, { text })
      await refresh()
    } catch (caught) {
      if (mounted.current)
        setActionError(getApiErrorMessage(caught, "Couldn't save that idea."))
    } finally {
      if (mounted.current) setCapturing(false)
    }
  }

  function handlePromote(idea: IncrementIdea) {
    if (disabled) return
    // Compose, don't mutate: prefill the increment input so the user confirms /
    // expands the idea into a ≥ 8-char feature request and submits it.
    setFeature(idea.text)
    setFeatureError(null)
    composeRef.current?.focus()
  }

  async function handlePush(increment: Increment) {
    if (disabled) return
    setPushingId(increment.id)
    setActionError(null)
    try {
      await pushIncrement(workspaceId, increment.id)
      await refresh()
    } catch (caught) {
      if (!mounted.current) return
      const status =
        typeof caught === "object" && caught !== null && "response" in caught
          ? (caught as { response?: { status?: number } }).response?.status
          : undefined
      setActionError(
        status === 409
          ? "Export this workspace to GitHub before pushing an increment."
          : status === 503
            ? "Background processing is unavailable — try again shortly."
            : getApiErrorMessage(caught, "Couldn't start the push. Please try again."),
      )
    } finally {
      if (mounted.current) setPushingId(null)
    }
  }

  if (loading && increments.length === 0 && ideas.length === 0) {
    return (
      <div className="ws-panel-section ws-timeline-panel" aria-busy="true">
        <div className="ws-panel-title">Increments</div>
        <div className="ws-timeline-skeleton" aria-hidden="true">
          <span className="ws-timeline-skeleton-bar" />
          <span className="ws-timeline-skeleton-node" />
          <span className="ws-timeline-skeleton-node" />
        </div>
      </div>
    )
  }

  // Enabled on any text; the ≥ 8-char rule surfaces as a calm hint on submit
  // rather than a silently disabled button with no explanation.
  const canSubmit = feature.trim().length > 0 && !creating && !disabled
  const disabledReasonId = disabledReason ? "increment-timeline-disabled-reason" : undefined

  return (
    <div className="ws-panel-section ws-timeline-panel">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Increments</div>
          <p>Your workspace, version by version.</p>
        </div>
      </div>

      <div className="ws-timeline-compose">
        <textarea
          ref={composeRef}
          className="ws-timeline-input"
          value={feature}
          maxLength={FEATURE_MAX}
          rows={2}
          placeholder="What do you want to add?"
          aria-label="Describe the next increment"
          aria-describedby={disabled ? disabledReasonId : undefined}
          disabled={creating || disabled}
          title={disabled ? disabledReason : undefined}
          onChange={(e) => {
            setFeature(e.target.value)
            if (featureError) setFeatureError(null)
          }}
        />
        <div className="ws-timeline-compose-actions">
          {featureError && (
            <span className="ws-timeline-hint" role="alert">
              {featureError}
            </span>
          )}
          <button
            type="button"
            className="ws-timeline-add"
            disabled={!canSubmit}
            title={disabled ? disabledReason : undefined}
            aria-describedby={disabled ? disabledReasonId : undefined}
            onClick={() => void handleCreate()}
            aria-label="Add increment"
          >
            Add
          </button>
        </div>
      </div>
      {disabled && disabledReason ? (
        <p id={disabledReasonId} className="workspace-lock-inline-note">
          {disabledReason}
        </p>
      ) : null}

      {creating && (
        <div className="ws-timeline-creating">
          <StagedProgress stages={CREATE_STAGES} stageIndex={createStage} />
        </div>
      )}

      {createError && (
        <ActionAlertPanel
          severity="error"
          title="Increment could not be created"
          message={createError}
          recovery="Your baseline is unchanged. Try again when you are ready."
          source="Increments"
          onDismiss={() => setCreateError(null)}
          className="ws-timeline-error"
        />
      )}

      <ol className="ws-timeline">
        {increments.map((inc) => {
          const flash = justPushed.has(inc.id)
          const canPush =
            hasBaselinePush &&
            (inc.status === "ready" || inc.status === "stale")
          return (
            <li
              key={inc.id}
              className={`ws-timeline-node status-${inc.status}${
                flash ? " just-pushed" : ""
              }`}
            >
              <span className="ws-timeline-marker" aria-hidden="true">
                {inc.status === "pushed" ? (
                  <ShippedCheckIcon />
                ) : inc.status === "stale" ? (
                  <DriftIcon />
                ) : (
                  <span className="ws-timeline-dot" />
                )}
              </span>
              <div className="ws-timeline-body">
                <span className="ws-timeline-node-title">{inc.title}</span>
                <span className="ws-timeline-meta">
                  Increment {inc.sequence}
                  <span className="ws-timeline-meta-sep">·</span>
                  <span className={`ws-timeline-status status-${inc.status}`}>
                    {STATUS_LABEL[inc.status]}
                  </span>
                </span>
              </div>
              {canPush && (
                <button
                  type="button"
                  className="ws-timeline-push"
                  disabled={pushingId === inc.id || disabled}
                  title={disabled ? disabledReason : undefined}
                  aria-describedby={disabled ? disabledReasonId : undefined}
                  onClick={() => void handlePush(inc)}
                  aria-label={`Push increment ${inc.sequence} to GitHub`}
                >
                  {pushingId === inc.id ? "Pushing…" : "Push"}
                </button>
              )}
            </li>
          )
        })}

        {/* The baseline always anchors the bottom of the spine. */}
        <li className="ws-timeline-node baseline">
          <span className="ws-timeline-marker" aria-hidden="true">
            <span className="ws-timeline-dot" />
          </span>
          <div className="ws-timeline-body">
            <span className="ws-timeline-node-title">v1</span>
            <span className="ws-timeline-meta">Baseline · finalised</span>
          </div>
        </li>
      </ol>

      {actionError && (
        <ActionAlertPanel
          severity="error"
          title="Increment action failed"
          message={actionError}
          recovery="Your timeline is unchanged. Try the action again."
          source="Increments"
          onDismiss={() => setActionError(null)}
          className="ws-timeline-error"
        />
      )}

      <IdeaBacklog
        ideas={ideas}
        capturing={capturing}
        onCapture={(text) => void handleCapture(text)}
        onPromote={handlePromote}
        disabled={disabled}
        disabledReason={disabledReason}
      />
    </div>
  )
}

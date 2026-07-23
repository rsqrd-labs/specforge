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
 * which prefills the input for confirmation and carries the idea identity into
 * increment creation so the backend can link it to the generated version.
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

const FEATURE_MIN = 20
const FEATURE_MIN_WORDS = 4
const FEATURE_MIN_DISTINCT_WORDS = 3
const FEATURE_MAX = 4000

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

function featureRequestError(value: string): string | null {
  const normalised = value.trim().replace(/\s+/g, " ")
  if (!normalised) return null
  const words = normalised.match(/[\p{L}][\p{L}\p{N}'’-]*/gu) ?? []
  const distinctWords = new Set(words.map((word) => word.toLocaleLowerCase()))
  if (
    normalised.length < FEATURE_MIN ||
    words.length < FEATURE_MIN_WORDS ||
    distinctWords.size < FEATURE_MIN_DISTINCT_WORDS
  ) {
    return "Describe a specific change in at least 4 words and 20 characters."
  }
  return null
}

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, "0")}`
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
  const [loadError, setLoadError] = useState<string | null>(null)

  const [feature, setFeature] = useState("")
  const [sourceIdea, setSourceIdea] = useState<IncrementIdea | null>(null)
  const [featureError, setFeatureError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [generationElapsed, setGenerationElapsed] = useState(0)
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
    try {
      const [incs, backlog] = await Promise.all([
        listIncrements(workspaceId),
        listIdeas(workspaceId),
      ])
      if (!mounted.current) return
      setIncrements(incs)
      setIdeas(backlog)
      setLoadError(null)
    } catch (caught) {
      if (!mounted.current) return
      setLoadError(
        getApiErrorMessage(
          caught,
          "We couldn't load your versions and saved ideas.",
        ),
      )
    } finally {
      if (mounted.current) setLoading(false)
    }
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

  // Show real elapsed time instead of simulating backend stages the synchronous
  // endpoint cannot actually report.
  useEffect(() => {
    if (!creating) return undefined
    const startedAt = Date.now()
    setGenerationElapsed(0)
    const timer = window.setInterval(() => {
      setGenerationElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [creating])

  async function handleCreate() {
    if (disabled) return
    const text = feature.trim()
    const validationError = featureRequestError(text)
    if (validationError) {
      setFeatureError(validationError)
      return
    }
    setFeatureError(null)
    setCreateError(null)
    setCreating(true)
    try {
      await createIncrement(workspaceId, {
        feature_request: text,
        mode: "additive",
        ...(sourceIdea ? { idea_id: sourceIdea.id } : {}),
      })
      if (!mounted.current) return
      setFeature("")
      setSourceIdea(null)
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
            ? sourceIdea
              ? "That saved idea has already been used. Refresh and choose another idea."
              : "Finalise all four stages before adding an increment."
            : status === 422
              ? "The request was too vague or did not produce a concrete task delta. Describe the change, affected user, and expected outcome."
              : getApiErrorMessage(caught, "Couldn't generate the increment. Please try again."),
      )
    } finally {
      if (mounted.current) setCreating(false)
    }
  }

  async function handleCapture(text: string): Promise<boolean> {
    if (disabled) return false
    setCapturing(true)
    setActionError(null)
    try {
      await createIdea(workspaceId, { text })
      await refresh()
      return true
    } catch (caught) {
      if (mounted.current)
        setActionError(getApiErrorMessage(caught, "Couldn't save that idea."))
      return false
    } finally {
      if (mounted.current) setCapturing(false)
    }
  }

  function handlePromote(idea: IncrementIdea) {
    if (disabled) return
    // Prefill for confirmation and expansion; the idea is linked only after a
    // sufficiently scoped request generates successfully.
    setFeature(idea.text)
    setSourceIdea(idea)
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

  const nextVersion = increments.reduce(
    (highest, increment) => Math.max(highest, increment.sequence + 2),
    2,
  )
  const liveFeatureError = featureRequestError(feature)
  // Keep an invalid action unavailable while the adjacent hint explains
  // exactly what is missing. The backend repeats this validation authoritatively.
  const canSubmit =
    feature.trim().length > 0 &&
    liveFeatureError === null &&
    !creating &&
    !disabled
  const disabledReasonId = disabledReason ? "increment-timeline-disabled-reason" : undefined

  return (
    <section className="ws-panel-section ws-timeline-panel" aria-labelledby="workspace-versions-title">
      <div className="ws-panel-section-header">
        <div>
          <div className="ws-panel-title">Workspace versions</div>
          <h2 id="workspace-versions-title" className="ws-timeline-heading">
            Build the next version
          </h2>
          <p>
            Describe one focused change. Thought2Build will turn it into new tasks
            without rewriting your completed baseline.
          </p>
        </div>
      </div>

      {loadError && (
        <ActionAlertPanel
          severity="error"
          title="Versions could not be loaded"
          message={loadError}
          recovery="Your workspace data is unchanged. Retry the connection."
          source="Workspace versions"
          primaryAction={{ label: "Retry", onSelect: () => refresh() }}
          className="ws-timeline-error"
        />
      )}

      <div className="ws-timeline-compose" aria-busy={creating}>
        <div className="ws-timeline-field-header">
          <label htmlFor="next-version-request">What should change?</label>
          <span>Creates Version {nextVersion}</span>
        </div>
        {sourceIdea && (
          <div className="ws-timeline-source-idea" role="status">
            <span>
              Using saved idea: <strong>{sourceIdea.text}</strong>
            </span>
            <button
              type="button"
              onClick={() => setSourceIdea(null)}
              disabled={creating}
              aria-label="Stop using saved idea"
            >
              Remove
            </button>
          </div>
        )}
        <textarea
          id="next-version-request"
          ref={composeRef}
          className="ws-timeline-input"
          value={feature}
          maxLength={FEATURE_MAX}
          rows={2}
          placeholder="For example: Add team invitations with role-based access"
          aria-label="What should change in the next version?"
          aria-describedby={disabled ? disabledReasonId : undefined}
          disabled={creating || disabled}
          title={disabled ? disabledReason : undefined}
          onChange={(e) => {
            setFeature(e.target.value)
            if (featureError) setFeatureError(null)
          }}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault()
              if (canSubmit) void handleCreate()
            }
          }}
        />
        <div className="ws-timeline-compose-actions">
          {featureError && (
            <span className="ws-timeline-hint" role="alert">
              {featureError}
            </span>
          )}
          {!featureError && liveFeatureError && (
            <span className="ws-timeline-hint">
              {liveFeatureError}
            </span>
          )}
          <span className="ws-timeline-shortcut" aria-hidden="true">
            {feature.length}/{FEATURE_MAX} · ⌘ Enter
          </span>
          <button
            type="button"
            className="ws-timeline-add"
            disabled={!canSubmit}
            title={disabled ? disabledReason : undefined}
            aria-describedby={disabled ? disabledReasonId : undefined}
            onClick={() => void handleCreate()}
            aria-label={`Generate Version ${nextVersion}`}
          >
            {creating ? "Generating…" : "Generate version"}
          </button>
        </div>
      </div>
      {disabled && disabledReason ? (
        <p id={disabledReasonId} className="workspace-lock-inline-note">
          {disabledReason}
        </p>
      ) : null}

      {creating && (
        <div className="ws-timeline-creating" role="status" aria-live="polite">
          <span className="ws-timeline-creating-indicator" aria-hidden="true" />
          <div>
            <strong>Generating Version {nextVersion}</strong>
            <p>
              Building a task-only delta from your finalised workspace. This
              usually takes 1–2 minutes and stops after the server timeout.
            </p>
          </div>
          <time dateTime={`PT${generationElapsed}S`} aria-hidden="true">
            {formatElapsed(generationElapsed)}
          </time>
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

      <div className="ws-timeline-section-heading">
        <span>Version history</span>
        <span>{increments.length + 1} version{increments.length === 0 ? "" : "s"}</span>
      </div>

      {increments.length === 0 && !loadError && (
        <p className="ws-timeline-empty">
          Version 1 is your completed baseline. Your first focused change will
          appear here as Version 2.
        </p>
      )}

      <ol className="ws-timeline" aria-label="Workspace version history">
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
                <span className="ws-timeline-version">Version {inc.sequence + 1}</span>
                <span className="ws-timeline-node-title">{inc.title}</span>
                <span className="ws-timeline-meta">
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
                  {pushingId === inc.id ? "Starting…" : "Push to GitHub"}
                </button>
              )}
              {!hasBaselinePush && (inc.status === "ready" || inc.status === "stale") && (
                <span className="ws-timeline-push-note" title="Export Version 1 to GitHub first">
                  Export Version 1 first
                </span>
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
            <span className="ws-timeline-version">Version 1</span>
            <span className="ws-timeline-node-title">Original workspace</span>
            <span className="ws-timeline-meta">Finalised baseline</span>
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
        onCapture={handleCapture}
        onPromote={handlePromote}
        selectedIdeaId={sourceIdea?.id}
        disabled={disabled}
        disabledReason={disabledReason}
      />
    </section>
  )
}

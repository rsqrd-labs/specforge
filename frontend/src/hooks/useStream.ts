import { useCallback, useEffect, useRef, useState } from "react"
import {
  cancelStageGeneration,
  generateStage,
  getStage,
  getStageGeneration,
  regenerateStage,
  regenerateStageForGaps,
  resumeStage,
} from "../services/api"
import {
  StreamError,
  createSSEConnection,
  type GenerationStartedInfo,
  type GenerationTerminalInfo,
} from "../services/sseService"
import { useStageStore } from "../store/stageStore"
import type { EvalResult, Stage } from "../types/stage"

type StreamAction = "generate" | "regenerate" | "regenerate-gaps" | "resume"

// docs/CRITIC_ASYNC_ADVISORY_PLAN.md §3.4: the critic now runs OFF the critical
// path and attaches its advisory findings to Stage.quality_gate a few seconds
// AFTER `done`. The single post-`done` refetch (below) is therefore too early to
// see them, so we follow it with a short bounded poll that stops the instant the
// findings land. No new SSE event — the stream still ends cleanly at `done`.
const ADVISORY_POLL_ATTEMPTS = 3
const ADVISORY_POLL_DELAY_MS = 4000

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

interface StreamResult {
  stage: Stage
  evalResult: EvalResult | null
}

export interface StreamErrorState {
  code: string
  message: string
}

export function useStream(stageId: string | null) {
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<StreamErrorState | null>(null)
  const [generation, setGeneration] = useState<GenerationStartedInfo | null>(null)
  const [terminal, setTerminal] = useState<GenerationTerminalInfo | null>(null)
  const [isStopping, setIsStopping] = useState(false)
  const streamRef = useRef<{ close: () => void } | null>(null)
  // #3b: `error` is shared across stage navigations — Workspace calls this hook
  // with `activeStage.id`, so the same hook instance serves every stage. Track
  // the live stageId so a stream that settles with an error AFTER the user
  // navigated away can't write it onto the stage they're now viewing, which would
  // bind that stage's "Try again" to the wrong generation and charge it.
  const currentStageIdRef = useRef(stageId)
  currentStageIdRef.current = stageId
  // Cancellation token for the in-flight post-`done` advisory poll. A new
  // generation (or unmount) flips `cancelled` so a stale poll can never write
  // findings onto a superseded stage.
  const advisoryPollRef = useRef<{ cancelled: boolean } | null>(null)

  useEffect(() => {
    return () => {
      streamRef.current?.close()
      // Closing the fetch aborts the SSE read. sseService now settles the
      // awaited `start()` promise on that abort (via onAbort), so the frame
      // unwinds and no longer leaks — but its rejection lands on a microtask,
      // AFTER a synchronous remount could re-hydrate this buffer OVER the
      // finished artifact the reconnect poll delivers (and a keystroke would
      // then persist that stale partial server-side). Discard the orphaned
      // client buffer synchronously here to win that remount race.
      const active = useStageStore.getState().activeStream
      if (active) {
        useStageStore.getState().discardStream(active)
      }
      if (advisoryPollRef.current) {
        advisoryPollRef.current.cancelled = true
      }
    }
  }, [])

  // Clear a stale error when the user navigates to a different stage (#3b): an
  // alert from a failed generation on stage A must never persist onto stage B,
  // where its "Try again" would charge B. Each stage owns its own error state.
  useEffect(() => {
    setError(null)
  }, [stageId])

  // Poll the stage after `done` until the async critic's advisory findings land
  // (or a bounded number of attempts elapse). Best-effort and detached: errors
  // are swallowed and it never blocks the returned StreamResult. `baseline` is
  // the advisory-findings count already present at `done` (e.g. a compression
  // notice); we stop the instant the count GROWS — counting, not just the
  // "advisory" status, so the critic merging findings into an existing notice
  // is detected too.
  const pollForAdvisoryFindings = useCallback((id: string, baseline: number) => {
    if (advisoryPollRef.current) {
      advisoryPollRef.current.cancelled = true
    }
    const token = { cancelled: false }
    advisoryPollRef.current = token
    void (async () => {
      for (let attempt = 0; attempt < ADVISORY_POLL_ATTEMPTS; attempt += 1) {
        await sleep(ADVISORY_POLL_DELAY_MS)
        if (token.cancelled) return
        try {
          const fresh = await getStage(id)
          if (token.cancelled) return
          useStageStore.getState().setStage(fresh)
          const findings =
            fresh.quality_gate?.status === "advisory"
              ? (fresh.quality_gate.findings?.length ?? 0)
              : 0
          if (findings > baseline) return
        } catch {
          // Best-effort: a transient failure just means we try again or time out.
        }
      }
    })()
  }, [])

  const start = useCallback(
    async (action: StreamAction = "generate"): Promise<StreamResult | null> => {
      if (!stageId) {
        return null
      }

      setError(null)
      setTerminal(null)
      setIsStopping(false)
      setIsStreaming(true)

      // A fresh generation supersedes any advisory poll still running for a
      // prior version of this (or another) stage.
      if (advisoryPollRef.current) {
        advisoryPollRef.current.cancelled = true
      }

      const store = useStageStore.getState()
      const existing = store.stages[stageId]
      // The stage version BEFORE this generation. A successful generation, a
      // quality-gate block, and a gap-patch all bump current_version at persist;
      // a provider/validation failure resets to draft WITHOUT bumping. That makes
      // the version the reliable "did work actually land?" signal used to
      // reconcile an interrupted stream WITHOUT ever re-POSTing (RC-2).
      const existingVersion = existing?.current_version ?? -1
      if (existing) {
        // Null the elapsed stamps in the optimistic flip (#5): `existing` still
        // carries the PREVIOUS run's `generation_started_at`, and the overlay's
        // reconnect baseline prefers that stamp when the stage is in_progress. If
        // `isStreaming` clears while this optimistic stage is still in the store
        // (a post-`done` refetch failure, or an offline reconcile), the overlay
        // would otherwise compute elapsed from the prior generation's start and
        // show a wildly wrong "41:07". Cleared here, it falls back to the pinned
        // `updated_at` baseline until the server supplies the real start.
        store.setStage({
          ...existing,
          status: "in_progress",
          generation_started_at: null,
          generation_action: null,
        })
      }
      store.startStream(stageId)

      // Per-invocation connection handle. Captured locally (not just in the
      // shared ref) so THIS call's teardown always closes ITS OWN connection —
      // a superseding start() that overwrote `streamRef` can't make our
      // `finally` close its stream instead (RC-4 hygiene).
      let connection: { close: () => void } | null = null
      const closeConnection = () => {
        connection?.close()
        if (streamRef.current === connection) {
          streamRef.current = null
        }
      }

      // Surface an error only if THIS invocation's stage is still the active one
      // (#3b): the stream may settle after the user navigated away, and writing
      // its error onto the now-active stage would mis-bind that stage's retry.
      const settleError = (state: StreamErrorState) => {
        if (currentStageIdRef.current === stageId) {
          setError(state)
        }
      }

      // The shared post-`done` tail: deliver the persisted artifact and start the
      // advisory-findings poll. Reused by the clean `done` path and by the
      // reconcile "work landed" path. `discardStream` (not `finaliseStream`)
      // drops the streamed buffer and lets `setStage(fresh)` supply the
      // authoritative content in the same synchronous batch — so a *partial*
      // buffer from an interrupted stream never flashes into the editor.
      const runDoneTail = async (
        settledStageId: string,
      ): Promise<StreamResult> => {
        const fresh = await getStage(settledStageId)
        const s = useStageStore.getState()
        s.discardStream(stageId)
        s.setStage(fresh)
        const baselineFindings =
          fresh.quality_gate?.status === "advisory"
            ? (fresh.quality_gate.findings?.length ?? 0)
            : 0
        pollForAdvisoryFindings(settledStageId, baselineFindings)
        return { stage: fresh, evalResult: null }
      }

      try {
        const response =
          action === "regenerate"
            ? await regenerateStage(stageId)
            : action === "regenerate-gaps"
              ? await regenerateStageForGaps(stageId)
              : action === "resume"
                ? await resumeStage(stageId)
                : await generateStage(stageId)

        const doneStageId = await new Promise<string>((resolve, reject) => {
          // Defense in depth: close any prior connection before overwriting the
          // shared ref (the synchronous activity guards in Workspace already
          // prevent a concurrent start(), so this is belt-and-braces).
          streamRef.current?.close()
          connection = createSSEConnection({
            url: response.stream_url,
            onToken: (token) => useStageStore.getState().appendToken(stageId, token),
            onDone: resolve,
            onError: reject,
            // Eval is not consumed from the stream: the independent stage-eval
            // poller in Workspace fetches it once the stage reaches draft. See
            // the done-handling note below.
            onEval: () => {},
            onQualityGateFailed: (info) =>
              useStageStore.getState().setQualityGate(stageId, info),
            onProgress: (progress) =>
              useStageStore.getState().setStreamProgress(stageId, progress),
            onGenerationStarted: (info) => {
              setGeneration(info)
              useStageStore.getState().setStreamProgress(stageId, {
                stage: existing?.type ?? "",
                state: "generating",
                phase: "preparing",
                elapsed_seconds: 0,
                completed_parts: 0,
                total_parts: info.total_parts,
                generation_id: info.generation_id,
                deadline: info.deadline,
                last_server_progress: new Date().toISOString(),
              })
            },
            onGenerationTerminal: (info) => {
              setTerminal(info)
              setIsStopping(false)
            },
            onReset: () => useStageStore.getState().clearStreamContent(stageId),
            // onAbort: the connection was torn down (unmount, cancel(), or a
            // superseding generation) before a terminal done/error. Settle this
            // executor so the frame unwinds and its `finally` runs — the
            // alternative is a Promise that never resolves and leaks this whole
            // closure for the connection's lifetime.
            onAbort: () =>
              reject(
                new StreamError("stream_aborted", "Generation stream was cancelled."),
              ),
          })
          streamRef.current = connection
        })

        // `done` is terminal for the loading UI — the backend persists the stage
        // (status=draft, version bumped, committed) *before* it emits `done`, and
        // commits the deterministic structural eval row before `done` too (issue
        // #27 Phase 1). Tear the stream down now instead of holding it open for
        // the eval tail: the stage-eval poller fetches the eval once the stage
        // reaches draft (structural findings are already there; the best-effort
        // LLM score updates the same row in the background), so closing the
        // stream never drops it.
        closeConnection()
        try {
          return await runDoneTail(doneStageId)
        } catch {
          // A2: the generation SUCCEEDED and `done` fired, but the confirming
          // refetch failed (runDoneTail threw at getStage, before its own
          // discard). Drop the orphaned streamed buffer + activeStream so they
          // don't leak — the store still holds the optimistic `in_progress`
          // stage, so `useReconnectPoll` delivers the persisted draft on its next
          // tick. Do NOT surface an error or regress to pre-generation content:
          // self-healing with zero fabricated state (Fable A2 variant).
          useStageStore.getState().discardStream(stageId)
          return null
        }
      } catch (streamError) {
        const code =
          streamError instanceof StreamError ? streamError.code : "internal_error"

        // A deliberate teardown (unmount cleanup, cancel(), or a superseding
        // generation) aborts the connection; sseService settles this executor
        // with the sentinel so the frame can unwind. There's no error to show
        // and no server state to reconcile — the caller that invoked close()
        // owns the follow-up (the unmount cleanup discards the buffer; cancel()
        // finalises it) — so bail without touching stage state or the error UI.
        if (code === "stream_aborted") {
          return null
        }

        if (
          code === "generation_cancelled" ||
          code === "generation_timed_out" ||
          code === "generation_failed" ||
          code === "generation_blocked"
        ) {
          useStageStore.getState().discardStream(stageId)
          try {
            useStageStore.getState().setStage(await getStage(stageId))
          } catch {
            // The durable run remains queryable; reconnect polling will retry.
          }
          return null
        }

        // RC-2: an interrupted connection (any drop after a Response existed) or
        // a duplicate-trigger `generation_in_progress` MUST NOT re-POST — that is
        // the double-charge hazard. Reconcile against the persisted stage using
        // the version bump as the signal, never a blind retry.
        if (code === "stream_interrupted" || code === "generation_in_progress") {
          try {
            const fresh = await getStage(stageId)
            const s = useStageStore.getState()
            if (fresh.status === "in_progress") {
              // Still running server-side — hand off to the reconnect overlay +
              // poll, which engage the moment `isStreaming` clears below.
              s.discardStream(stageId)
              s.setStage(fresh)
              return null
            }
            if (fresh.current_version > existingVersion) {
              // Work landed (a completed draft or a quality-gate block) — deliver
              // it exactly as a clean `done` would. One generation, one charge.
              return await runDoneTail(stageId)
            }
            // Version unchanged ⇒ the generation failed and was refunded
            // server-side (or a gap-patch rolled back). Surface a user-consented
            // "Try again" — but only when the stage is still generatable; a stage
            // another tab finalised meanwhile can't be retried.
            s.discardStream(stageId)
            s.setStage(fresh)
            if (fresh.status === "draft" || fresh.status === "stale") {
              settleError({
                code: "stream_interrupted",
                message:
                  streamError instanceof Error
                    ? streamError.message
                    : "The generation was interrupted.",
              })
            }
            return null
          } catch {
            // Couldn't reconcile (the refetch itself failed). Drop the partial
            // and let the user retry — never regress to pre-generation content.
            useStageStore.getState().discardStream(stageId)
            settleError({
              code: "stream_interrupted",
              message:
                "We couldn't confirm whether the generation finished. " +
                "Refresh or try again.",
            })
            return null
          }
        }

        // Genuine terminal error (timeout, unavailable, security, gate, etc.):
        // the stage was reset to draft server-side, so refetch the truth.
        useStageStore.getState().finaliseStream(stageId)
        const message =
          streamError instanceof Error ? streamError.message : "Streaming failed"
        settleError({ code, message })

        try {
          const latestStage = await getStage(stageId)
          useStageStore.getState().setStage(latestStage)
        } catch {
          if (existing) {
            useStageStore.getState().setStage(existing)
          }
        }

        return null
      } finally {
        closeConnection()
        setIsStreaming(false)
      }
    },
    [stageId, pollForAdvisoryFindings],
  )

  const cancel = useCallback(async () => {
    if (!stageId) return
    setError(null)
    try {
      const active = generation ?? (await getStageGeneration(stageId))
      if (!active || ("status" in active && active.status !== "running")) {
        setError({
          code: "cancellation_failed",
          message: "This generation is no longer active.",
        })
        return
      }
      setIsStopping(true)
      const generationId =
        "generation_id" in active ? active.generation_id : active.id
      const run = await cancelStageGeneration(stageId, generationId)
      setGeneration({
        generation_id: run.id,
        deadline: run.deadline_at,
        action: run.action,
        total_parts: run.total_parts,
      })
      useStageStore.getState().setStreamProgress(stageId, {
        stage: useStageStore.getState().stages[stageId]?.type ?? "",
        state: "generating",
        phase: "stopping",
        elapsed_seconds: Math.max(
          0,
          Math.floor((Date.now() - Date.parse(run.started_at)) / 1000),
        ),
        completed_parts: run.completed_parts,
        total_parts: run.total_parts,
        generation_id: run.id,
        deadline: run.deadline_at,
        last_server_progress: run.heartbeat_at,
      })
    } catch (cancelError) {
      setIsStopping(false)
      setError({
        code: "cancellation_failed",
        message:
          cancelError instanceof Error
            ? cancelError.message
            : "Cancellation could not be requested. Try again.",
      })
    }
  }, [generation, stageId])

  return { start, cancel, isStreaming, isStopping, generation, terminal, error }
}

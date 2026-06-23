import { useCallback, useEffect, useRef, useState } from "react"
import {
  generateStage,
  getStage,
  regenerateStage,
  regenerateStageForGaps,
} from "../services/api"
import { StreamError, closeStreamRef, createSSEConnection } from "../services/sseService"
import { useStageStore } from "../store/stageStore"
import type { EvalResult, Stage } from "../types/stage"

type StreamAction = "generate" | "regenerate" | "regenerate-gaps"

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
  const streamRef = useRef<{ close: () => void } | null>(null)
  // Cancellation token for the in-flight post-`done` advisory poll. A new
  // generation (or unmount) flips `cancelled` so a stale poll can never write
  // findings onto a superseded stage.
  const advisoryPollRef = useRef<{ cancelled: boolean } | null>(null)

  useEffect(() => {
    return () => {
      streamRef.current?.close()
      if (advisoryPollRef.current) {
        advisoryPollRef.current.cancelled = true
      }
    }
  }, [])

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
      setIsStreaming(true)

      // A fresh generation supersedes any advisory poll still running for a
      // prior version of this (or another) stage.
      if (advisoryPollRef.current) {
        advisoryPollRef.current.cancelled = true
      }

      const store = useStageStore.getState()
      const existing = store.stages[stageId]
      if (existing) {
        store.setStage({ ...existing, status: "in_progress" })
      }
      store.startStream(stageId)

      try {
        const response =
          action === "regenerate"
            ? await regenerateStage(stageId)
            : action === "regenerate-gaps"
              ? await regenerateStageForGaps(stageId)
              : await generateStage(stageId)

        const doneStageId = await new Promise<string>((resolve, reject) => {
          streamRef.current = createSSEConnection(
            response.stream_url,
            (token) => useStageStore.getState().appendToken(stageId, token),
            resolve,
            reject,
            // Eval is not consumed from the stream: the independent stage-eval
            // poller in Workspace fetches it once the stage reaches draft. See
            // the done-handling note below.
            () => {},
            (info) => useStageStore.getState().setQualityGate(stageId, info),
            (progress) =>
              useStageStore.getState().setStreamProgress(stageId, progress),
            () => useStageStore.getState().clearStreamContent(stageId),
          )
        })

        // `done` is terminal for the loading UI — the backend persists the stage
        // (status=draft, version bumped, committed) *before* it emits `done`, and
        // commits the deterministic structural eval row before `done` too (issue
        // #27 Phase 1). Tear the stream down now instead of holding it open for
        // the eval tail: the stage-eval poller fetches the eval once the stage
        // reaches draft (structural findings are already there; the best-effort
        // LLM score updates the same row in the background), so closing the
        // stream never drops it.
        closeStreamRef(streamRef)
        useStageStore.getState().finaliseStream(stageId)
        const updatedStage = await getStage(doneStageId)
        useStageStore.getState().setStage(updatedStage)

        // The async critic attaches its advisory findings shortly after `done`
        // (docs/CRITIC_ASYNC_ADVISORY_PLAN.md §3.4), so the refetch above is too
        // early to see them. Poll briefly until they land (counting past any
        // notice already attached at `done`) so they surface without a manual
        // refresh. Harmless on the legacy inline path — findings are already
        // present, so the first poll sees no growth and it quietly times out.
        const baselineFindings =
          updatedStage.quality_gate?.status === "advisory"
            ? (updatedStage.quality_gate.findings?.length ?? 0)
            : 0
        pollForAdvisoryFindings(doneStageId, baselineFindings)

        return { stage: updatedStage, evalResult: null }
      } catch (streamError) {
        useStageStore.getState().finaliseStream(stageId)
        const message =
          streamError instanceof Error ? streamError.message : "Streaming failed"
        const code =
          streamError instanceof StreamError ? streamError.code : "internal_error"
        setError({ code, message })

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
        closeStreamRef(streamRef)
        setIsStreaming(false)
      }
    },
    [stageId],
  )

  const cancel = useCallback(() => {
    closeStreamRef(streamRef)
    if (stageId) {
      useStageStore.getState().finaliseStream(stageId)
    }
    setIsStreaming(false)
  }, [stageId])

  return { start, cancel, isStreaming, error }
}

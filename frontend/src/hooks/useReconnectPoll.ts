import { useEffect } from "react"

import { getStage, getStageGeneration } from "../services/api"
import { useStageStore } from "../store/stageStore"
import type { GenerationRun } from "../types/stage"

// Reconnect-by-poll for a generation that is still running server-side after a
// page refresh (docs/REFRESH_DURING_GENERATION_PLAN.md). A refresh closes the
// SSE connection, but the server keeps the detached generation pipeline running
// and persists the finished artifact at `done`. A client that did NOT start the
// stream (true on a fresh mount) polls the stage until it leaves `in_progress`,
// then writes the settled result into the store so the completed draft — or a
// quality-gate block — appears without a manual re-generate.
//
// This delivers the persisted artifact, not the token-by-token animation: live
// streaming resume across a refresh needs a Redis pub/sub fan-out and is
// deliberately deferred.
// Fast cadence for the common short generation…
export const RECONNECT_POLL_DELAY_MS = 3000
// …stepping down to a calmer cadence once a run is clearly long-tail, so a
// frontier generation that legitimately takes minutes isn't polled every 3s for
// its whole life.
export const RECONNECT_POLL_SLOW_DELAY_MS = 10000
export const RECONNECT_POLL_SLOWDOWN_AFTER_MS = 120_000
// Total lifetime exceeds the configured generation deadline plus its
// 30-second recovery grace. The recovery sweep terminalises any run that misses
// that bound, so reconnect polling never silently abandons an active overlay.
export const RECONNECT_POLL_MAX_MS = 6 * 60 * 1000

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Poll a server-side in-progress stage to completion when this client is not the
 * one streaming it.
 *
 * @param stageId    the id of the stage currently `in_progress`, or null
 * @param isStreaming true when THIS client owns the live SSE stream (so it must
 *                    not poll — the stream hook already drives the stage)
 */
export function useReconnectPoll(
  stageId: string | null,
  isStreaming: boolean,
  onTerminal?: (run: GenerationRun) => void,
): void {
  const setStage = useStageStore((state) => state.setStage)
  const setStreamProgress = useStageStore((state) => state.setStreamProgress)

  useEffect(() => {
    if (!stageId || isStreaming) return

    let cancelled = false
    const startedAt = Date.now()

    const pollUntilSettled = async () => {
      while (!cancelled && Date.now() - startedAt < RECONNECT_POLL_MAX_MS) {
        const delay =
          Date.now() - startedAt < RECONNECT_POLL_SLOWDOWN_AFTER_MS
            ? RECONNECT_POLL_DELAY_MS
            : RECONNECT_POLL_SLOW_DELAY_MS
        await sleep(delay)
        if (cancelled) return
        try {
          const run = await getStageGeneration(stageId)
          if (cancelled) return
          if (run?.status === "running") {
            setStreamProgress(stageId, {
              stage: "",
              state: "generating",
              phase: run.phase,
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
            continue
          }
          const fresh = await getStage(stageId)
          if (cancelled) return
          setStage(fresh)
          if (run) {
            if (run.status !== "succeeded") onTerminal?.(run)
            return
          }
          if (fresh.status !== "in_progress") return
        } catch (err) {
          if (cancelled) return
          // Transient read error — keep polling; the generation is still running
          // server-side and the recovery sweep is the backstop if it dies.
          console.warn("[reconnect] stage poll failed", stageId, err)
        }
      }
    }

    void pollUntilSettled()

    return () => {
      cancelled = true
    }
  }, [stageId, isStreaming, onTerminal, setStage, setStreamProgress])
}

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
// Absolute client safety bound. The server currently permits a 10-minute run;
// this intentionally exceeds it and the recovery grace. Once generation
// metadata arrives, the tighter server-provided deadline + grace is used.
export const RECONNECT_POLL_MAX_MS = 12 * 60 * 1000
export const RECONNECT_RECOVERY_GRACE_MS = 90 * 1000

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const settlementOverdue = (run: GenerationRun): GenerationRun => ({
  ...run,
  status: "timed_out",
  error_code: "generation_settlement_overdue",
})

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
    let stopAt = startedAt + RECONNECT_POLL_MAX_MS
    let lastRunning: GenerationRun | null = null

    const pollUntilSettled = async () => {
      while (!cancelled && Date.now() < stopAt) {
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
            lastRunning = run
            const serverDeadline = Date.parse(run.deadline_at)
            if (Number.isFinite(serverDeadline)) {
              // Never trust a malformed/far-future server value to poll forever;
              // the fixed 12-minute bound remains the outer safety ceiling.
              stopAt = Math.min(
                startedAt + RECONNECT_POLL_MAX_MS,
                serverDeadline + RECONNECT_RECOVERY_GRACE_MS,
              )
            }
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

      if (cancelled) return
      // The backend should have terminalised by deadline + recovery grace. Do
      // one final reconciliation so a boundary-time completion is not missed;
      // if the durable row is still running, surface a settlement-overdue state
      // instead of silently leaving the loading overlay forever.
      try {
        const run = await getStageGeneration(stageId)
        if (cancelled) return
        const fresh = await getStage(stageId)
        if (cancelled) return
        setStage(fresh)
        if (run && run.status !== "running") {
          if (run.status !== "succeeded") onTerminal?.(run)
          return
        }
        const overdue = run ?? lastRunning
        if (overdue) {
          onTerminal?.(settlementOverdue(overdue))
        }
      } catch (err) {
        if (!cancelled) {
          console.warn("[reconnect] final reconciliation failed", stageId, err)
          // The API can itself be transiently unavailable at the settlement
          // boundary. We still have a durable-running snapshot, so surface the
          // overdue state rather than ending this hook with no user feedback.
          if (lastRunning) onTerminal?.(settlementOverdue(lastRunning))
        }
      }
    }

    void pollUntilSettled()

    return () => {
      cancelled = true
    }
  }, [stageId, isStreaming, onTerminal, setStage, setStreamProgress])
}

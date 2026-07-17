import { useEffect } from "react"

import { getStage } from "../services/api"
import { useStageStore } from "../store/stageStore"

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
// Total lifetime. The previous fixed 240×3s = 12min cap UNDERSHOT a single
// stream's worst case: the 900s (15min) hard cap PLUS a mid-tier retry PLUS
// repairs. This bound comfortably exceeds that; past it, the server's 3-min
// stuck-stage recovery sweep is the backstop (it resets any stage left
// in_progress), so the overlay can never tick forever with no poll behind it.
export const RECONNECT_POLL_MAX_MS = 30 * 60 * 1000

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Poll a server-side in-progress stage to completion when this client is not the
 * one streaming it.
 *
 * @param stageId    the id of the stage currently `in_progress`, or null
 * @param isStreaming true when THIS client owns the live SSE stream (so it must
 *                    not poll — the stream hook already drives the stage)
 */
export function useReconnectPoll(stageId: string | null, isStreaming: boolean): void {
  const setStage = useStageStore((state) => state.setStage)

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
          const fresh = await getStage(stageId)
          if (cancelled) return
          setStage(fresh)
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
  }, [stageId, isStreaming, setStage])
}

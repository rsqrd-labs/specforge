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
export const RECONNECT_POLL_DELAY_MS = 3000
// The window comfortably outlasts a full four-stage generation (LLM call,
// quality gates, and a same-provider repair/escalation). If it lapses, the
// stuck-stage recovery sweep on the server is the backstop.
export const RECONNECT_POLL_ATTEMPTS = 240

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

    const pollUntilSettled = async () => {
      for (let attempt = 0; attempt < RECONNECT_POLL_ATTEMPTS; attempt += 1) {
        await sleep(RECONNECT_POLL_DELAY_MS)
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

import { useCallback, useEffect, useRef, useState } from "react"
import {
  generateStage,
  getStage,
  getStageEval,
  regenerateStage,
} from "../services/api"
import { createSSEConnection } from "../services/sseService"
import { useStageStore } from "../store/stageStore"
import type { EvalResult, Stage } from "../types/stage"

type StreamAction = "generate" | "regenerate"

interface StreamResult {
  stage: Stage
  evalResult: EvalResult | null
}

async function pollEval(stageId: string): Promise<EvalResult | null> {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      return await getStageEval(stageId)
    } catch {
      await new Promise((resolve) => window.setTimeout(resolve, 5_000))
    }
  }

  return null
}

export function useStream(stageId: string | null) {
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const streamRef = useRef<{ close: () => void } | null>(null)

  useEffect(() => {
    return () => {
      streamRef.current?.close()
    }
  }, [])

  const start = useCallback(
    async (action: StreamAction = "generate"): Promise<StreamResult | null> => {
      if (!stageId) {
        return null
      }

      setError(null)
      setIsStreaming(true)

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
            : await generateStage(stageId)

        const doneStageId = await new Promise<string>((resolve, reject) => {
          streamRef.current = createSSEConnection(
            response.stream_url,
            (token) => useStageStore.getState().appendToken(stageId, token),
            resolve,
            reject,
          )
        })

        useStageStore.getState().finaliseStream(stageId)
        const updatedStage = await getStage(doneStageId)
        useStageStore.getState().setStage(updatedStage)
        const evalResult = await pollEval(doneStageId)

        return { stage: updatedStage, evalResult }
      } catch (streamError) {
        useStageStore.getState().finaliseStream(stageId)
        const message =
          streamError instanceof Error ? streamError.message : "Streaming failed"
        setError(message)

        if (existing) {
          useStageStore.getState().setStage(existing)
        }

        return null
      } finally {
        streamRef.current = null
        setIsStreaming(false)
      }
    },
    [stageId],
  )

  const cancel = useCallback(() => {
    streamRef.current?.close()
    streamRef.current = null
    if (stageId) {
      useStageStore.getState().finaliseStream(stageId)
    }
    setIsStreaming(false)
  }, [stageId])

  return { start, cancel, isStreaming, error }
}

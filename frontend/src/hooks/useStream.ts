import { useCallback, useEffect, useRef, useState } from "react"
import {
  generateStage,
  getStage,
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

        let onEval!: (result: EvalResult | null) => void
        const evalPromise = new Promise<EvalResult | null>((resolve) => {
          onEval = resolve
        })

        const doneStageId = await new Promise<string>((resolve, reject) => {
          streamRef.current = createSSEConnection(
            response.stream_url,
             (token) => useStageStore.getState().appendToken(stageId, token),
             resolve,
             reject,
             onEval,
           )
        })

        useStageStore.getState().finaliseStream(stageId)
        const updatedStage = await getStage(doneStageId)
        useStageStore.getState().setStage(updatedStage)
        const evalResult = await evalPromise

        return { stage: updatedStage, evalResult }
      } catch (streamError) {
        useStageStore.getState().finaliseStream(stageId)
        const message =
          streamError instanceof Error ? streamError.message : "Streaming failed"
        setError(message)

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

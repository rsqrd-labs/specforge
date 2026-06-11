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
            : action === "regenerate-gaps"
              ? await regenerateStageForGaps(stageId)
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
             (info) => useStageStore.getState().setQualityGate(stageId, info),
             (progress) =>
               useStageStore.getState().setStreamProgress(stageId, progress),
             () => useStageStore.getState().clearStreamContent(stageId),
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

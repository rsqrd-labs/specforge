import { create } from "zustand"
import { subscribeWithSelector } from "zustand/middleware"
import type { Stage } from "../types/stage"

interface StageState {
  stages: Record<string, Stage>
  streamingContent: Record<string, string>
  activeStream: string | null
  setStage: (stage: Stage) => void
  setStages: (stages: Stage[]) => void
  appendToken: (stageId: string, token: string) => void
  startStream: (stageId: string) => void
  finaliseStream: (stageId: string) => void
}

export const useStageStore = create<StageState>()(
  subscribeWithSelector((set) => ({
    stages: {},
    streamingContent: {},
    activeStream: null,

    setStage: (stage) =>
      set((state) => ({
        stages: { ...state.stages, [stage.id]: stage },
      })),

    setStages: (stages) =>
      set((state) => ({
        stages: {
          ...state.stages,
          ...Object.fromEntries(stages.map((stage) => [stage.id, stage])),
        },
      })),

    appendToken: (stageId, token) =>
      set((state) => ({
        streamingContent: {
          ...state.streamingContent,
          [stageId]: (state.streamingContent[stageId] ?? "") + token,
        },
      })),

    startStream: (stageId) =>
      set((state) => ({
        activeStream: stageId,
        streamingContent: { ...state.streamingContent, [stageId]: "" },
      })),

    finaliseStream: (stageId) =>
      set((state) => {
        const accumulated = state.streamingContent[stageId]
        const existing = state.stages[stageId]
        const updatedStreamingContent = { ...state.streamingContent }
        delete updatedStreamingContent[stageId]

        return {
          activeStream: null,
          streamingContent: updatedStreamingContent,
          stages: existing
            ? {
                ...state.stages,
                [stageId]: {
                  ...existing,
                  content: accumulated ?? existing.content,
                },
              }
            : state.stages,
        }
      }),
  })),
)

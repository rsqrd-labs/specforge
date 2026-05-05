import { create } from "zustand"
import { subscribeWithSelector } from "zustand/middleware"
import type { Stage, StageType } from "../types/stage"

interface StageState {
  stages: Record<string, Stage>
  streamingContent: Record<string, string> | string
  activeStream: string | null
  setStage: (stage: Stage) => void
  setStages: (stages: Stage[]) => void
  appendToken: (stageId: string, token: string) => void
  appendStreamToken: (token: string) => void
  startStream: (stageId: string) => void
  finaliseStream: (stageId: string) => void
  markStale: (stageType: StageType) => void
}

const STAGE_ORDER: StageType[] = ["spec", "plan", "harness", "tasks"]

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
        streamingContent:
          typeof state.streamingContent === "string"
            ? state.streamingContent + token
            : {
                ...state.streamingContent,
                [stageId]: (state.streamingContent[stageId] ?? "") + token,
              },
      })),

    appendStreamToken: (token) =>
      set((state) => {
        if (typeof state.streamingContent === "string") {
          return { streamingContent: state.streamingContent + token }
        }

        const stageId = state.activeStream
        if (!stageId) return state
        return {
          streamingContent: {
            ...state.streamingContent,
            [stageId]: (state.streamingContent[stageId] ?? "") + token,
          },
        }
      }),

    startStream: (stageId) =>
      set((state) => ({
        activeStream: stageId,
        streamingContent:
          typeof state.streamingContent === "string"
            ? { [stageId]: "" }
            : { ...state.streamingContent, [stageId]: "" },
      })),

    finaliseStream: (stageId) =>
      set((state) => {
        const accumulated =
          typeof state.streamingContent === "string"
            ? state.streamingContent
            : state.streamingContent[stageId]
        const existing = state.stages[stageId]
        const updatedStreamingContent =
          typeof state.streamingContent === "string"
            ? ""
            : { ...state.streamingContent }
        if (typeof updatedStreamingContent !== "string") {
          delete updatedStreamingContent[stageId]
        }

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

    markStale: (stageType) =>
      set((state) => {
        const editedIndex = STAGE_ORDER.indexOf(stageType)
        if (editedIndex === -1) return state

        const stages = Object.fromEntries(
          Object.entries(state.stages).map(([key, stage]) => {
            const stageIndex = STAGE_ORDER.indexOf(stage.type)
            if (stageIndex > editedIndex && stage.status === "finalised") {
              return [key, { ...stage, status: "stale" as const }]
            }
            return [key, stage]
          }),
        )

        return { stages }
      }),
  })),
)

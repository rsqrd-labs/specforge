import { create } from "zustand"
import { subscribeWithSelector } from "zustand/middleware"
import type { QualityGateInfo, Stage, StageType } from "../types/stage"

interface StageState {
  stages: Record<string, Stage>
  /** Per-stage streaming buffer keyed by stage ID.  Narrowed from the former
   *  `Record<string,string>|string` union — all consumers use object access.
   *  M-6 — T-188.
   */
  streamingContent: Record<string, string>
  activeStream: string | null
  /** Critic quality-gate findings per stage ID, set when a generation is held
   *  back by the gate (T-247).  Cleared when a new stream starts for the stage. */
  qualityGate: Record<string, QualityGateInfo>
  setStage: (stage: Stage) => void
  setStages: (stages: Stage[]) => void
  appendToken: (stageId: string, token: string) => void
  appendStreamToken: (token: string) => void
  startStream: (stageId: string) => void
  finaliseStream: (stageId: string) => void
  setQualityGate: (stageId: string, info: QualityGateInfo) => void
  clearQualityGate: (stageId: string) => void
  markStale: (stageType: StageType) => void
}

const STAGE_ORDER: StageType[] = ["spec", "plan", "harness", "tasks"]

function blockedGate(stage: Stage): QualityGateInfo | null {
  return stage.quality_gate?.status === "blocked" ? stage.quality_gate : null
}

export const useStageStore = create<StageState>()(
  subscribeWithSelector((set) => ({
    stages: {},
    streamingContent: {},
    activeStream: null,
    qualityGate: {},

    setStage: (stage) =>
      set((state) => {
        const qualityGate = { ...state.qualityGate }
        const gate = blockedGate(stage)
        if (gate) {
          qualityGate[stage.id] = gate
        } else {
          delete qualityGate[stage.id]
        }
        return {
          stages: { ...state.stages, [stage.id]: stage },
          qualityGate,
        }
      }),

    setStages: (stages) =>
      set((state) => {
        const qualityGate = { ...state.qualityGate }
        for (const stage of stages) {
          const gate = blockedGate(stage)
          if (gate) {
            qualityGate[stage.id] = gate
          } else {
            delete qualityGate[stage.id]
          }
        }
        return {
          stages: {
            ...state.stages,
            ...Object.fromEntries(stages.map((stage) => [stage.id, stage])),
          },
          qualityGate,
        }
      }),

    appendToken: (stageId, token) =>
      set((state) => ({
        streamingContent: {
          ...state.streamingContent,
          [stageId]: (state.streamingContent[stageId] ?? "") + token,
        },
      })),

    appendStreamToken: (token) =>
      set((state) => {
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
      set((state) => {
        // Clear any prior gate findings for this stage on a fresh attempt.
        const qualityGate = { ...state.qualityGate }
        delete qualityGate[stageId]
        return {
          activeStream: stageId,
          streamingContent: { ...state.streamingContent, [stageId]: "" },
          qualityGate,
        }
      }),

    setQualityGate: (stageId, info) =>
      set((state) => ({
        qualityGate: {
          ...state.qualityGate,
          [stageId]: { ...info, status: "blocked" },
        },
      })),

    clearQualityGate: (stageId) =>
      set((state) => {
        const qualityGate = { ...state.qualityGate }
        delete qualityGate[stageId]
        return { qualityGate }
      }),

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

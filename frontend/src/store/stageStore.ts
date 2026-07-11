import { create } from "zustand"
import { subscribeWithSelector } from "zustand/middleware"
import type { GenerationProgress } from "../services/sseService"
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
  /** Latest backend liveness heartbeat per stage ID, emitted every ~10s while
   *  the generation pipeline works without producing visible tokens (frontier
   *  models reasoning, quality gates running).  Lets the UI show "still
   *  working" instead of a frozen loading screen — issue #19. */
  streamProgress: Record<string, GenerationProgress>
  /** stream_reset bookkeeping per stage ID. A reset (completion-repair,
   *  provider fallback, or the final canonical replay) means the live draft is
   *  about to be replaced — but the replacement does not stream during a repair,
   *  so emptying the buffer immediately blanks the editor and regresses the
   *  overlay from the slim "watch it grow" pill back to the full from-scratch
   *  loading card for the whole repair. Instead we keep the current draft on
   *  screen and overwrite it the moment the first replacement token arrives. */
  pendingReset: Record<string, boolean>
  setStage: (stage: Stage) => void
  setStages: (stages: Stage[]) => void
  appendToken: (stageId: string, token: string) => void
  appendStreamToken: (token: string) => void
  startStream: (stageId: string) => void
  finaliseStream: (stageId: string) => void
  setQualityGate: (stageId: string, info: QualityGateInfo) => void
  clearQualityGate: (stageId: string) => void
  setStreamProgress: (stageId: string, progress: GenerationProgress) => void
  /** stream_reset: the live-streamed draft is being replaced (repair or
   *  canonical replay) — empty the buffer without ending the stream. */
  clearStreamContent: (stageId: string) => void
  /** Drop the in-flight stream's client buffer WITHOUT persisting it into
   *  `stages[…].content`. Called when the streaming client tears down (Workspace
   *  unmount) before `done`: the detached backend pipeline keeps running and the
   *  reconnect poll delivers the final artifact, so the orphaned partial must not
   *  survive to be re-hydrated as a stale draft over the finished content. */
  discardStream: (stageId: string) => void
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
    streamProgress: {},
    pendingReset: {},

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
      set((state) => {
        // A pending reset means this token is the first of the replacement
        // draft: overwrite the (now-stale) buffer instead of appending, and
        // clear the reset flag.
        const resetting = state.pendingReset[stageId]
        const base = resetting ? "" : (state.streamingContent[stageId] ?? "")
        const pendingReset = { ...state.pendingReset }
        delete pendingReset[stageId]
        return {
          streamingContent: { ...state.streamingContent, [stageId]: base + token },
          pendingReset,
        }
      }),

    appendStreamToken: (token) =>
      set((state) => {
        const stageId = state.activeStream
        if (!stageId) return state
        const resetting = state.pendingReset[stageId]
        const base = resetting ? "" : (state.streamingContent[stageId] ?? "")
        const pendingReset = { ...state.pendingReset }
        delete pendingReset[stageId]
        return {
          streamingContent: { ...state.streamingContent, [stageId]: base + token },
          pendingReset,
        }
      }),

    startStream: (stageId) =>
      set((state) => {
        // Clear any prior gate findings for this stage on a fresh attempt.
        const qualityGate = { ...state.qualityGate }
        delete qualityGate[stageId]
        const streamProgress = { ...state.streamProgress }
        delete streamProgress[stageId]
        const pendingReset = { ...state.pendingReset }
        delete pendingReset[stageId]
        return {
          activeStream: stageId,
          streamingContent: { ...state.streamingContent, [stageId]: "" },
          qualityGate,
          streamProgress,
          pendingReset,
        }
      }),

    setStreamProgress: (stageId, progress) =>
      set((state) => ({
        streamProgress: { ...state.streamProgress, [stageId]: progress },
      })),

    clearStreamContent: (stageId) =>
      // Deferred reset: keep the current draft visible so the editor never
      // blanks (and the overlay never regresses to the from-scratch loading
      // card) during a repair that streams nothing until it completes. The
      // first replacement token (appendToken) overwrites the stale buffer.
      set((state) => ({
        pendingReset: { ...state.pendingReset, [stageId]: true },
      })),

    discardStream: (stageId) =>
      set((state) => {
        const streamingContent = { ...state.streamingContent }
        delete streamingContent[stageId]
        const streamProgress = { ...state.streamProgress }
        delete streamProgress[stageId]
        const pendingReset = { ...state.pendingReset }
        delete pendingReset[stageId]
        return {
          streamingContent,
          streamProgress,
          pendingReset,
          activeStream: state.activeStream === stageId ? null : state.activeStream,
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
        const streamProgress = { ...state.streamProgress }
        delete streamProgress[stageId]
        const pendingReset = { ...state.pendingReset }
        delete pendingReset[stageId]

        return {
          activeStream: null,
          streamingContent: updatedStreamingContent,
          streamProgress,
          pendingReset,
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

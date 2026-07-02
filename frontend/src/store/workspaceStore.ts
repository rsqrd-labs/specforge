import { create } from "zustand"
import {
  createWorkspace,
  deleteWorkspace as deleteWorkspaceRequest,
  getWorkspace,
  getWorkspaces,
  listTrashedWorkspaces,
  restoreWorkspace as restoreWorkspaceRequest,
} from "../services/api"
import type { TrashedWorkspace } from "../types/retention"
import type { CreateWorkspacePayload, Workspace, WorkspaceWithStages } from "../types/workspace"

interface WorkspaceState {
  workspaces: Workspace[]
  trashedWorkspaces: TrashedWorkspace[]
  currentWorkspace: WorkspaceWithStages | null
  isLoading: boolean
  fetchWorkspaces: () => Promise<void>
  fetchTrashed: () => Promise<void>
  fetchWorkspace: (id: string) => Promise<void>
  setCurrentWorkspace: (workspace: WorkspaceWithStages | null) => void
  createWorkspace: (payload: CreateWorkspacePayload) => Promise<WorkspaceWithStages>
  deleteWorkspace: (id: string, ackVersion?: string) => Promise<void>
  restoreWorkspace: (id: string) => Promise<void>
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  workspaces: [],
  trashedWorkspaces: [],
  currentWorkspace: null,
  isLoading: false,

  fetchWorkspaces: async () => {
    set({ isLoading: true })
    try {
      const workspaces = await getWorkspaces()
      set({ workspaces, isLoading: false })
    } catch {
      set({ isLoading: false })
    }
  },

  fetchTrashed: async () => {
    // Best-effort: a trash-list failure must never block the dashboard. On error
    // the section simply stays empty (retention is additive).
    try {
      const trashedWorkspaces = await listTrashedWorkspaces()
      set({ trashedWorkspaces })
    } catch {
      set({ trashedWorkspaces: [] })
    }
  },

  fetchWorkspace: async (id) => {
    set({ isLoading: true })
    try {
      const workspace = await getWorkspace(id)
      set({ currentWorkspace: workspace, isLoading: false })
    } catch {
      set({ isLoading: false })
    }
  },

  setCurrentWorkspace: (workspace) => set({ currentWorkspace: workspace }),

  createWorkspace: async (payload) => {
    const workspace = await createWorkspace(payload)
    set((state) => ({ workspaces: [workspace, ...state.workspaces] }))
    return workspace
  },

  deleteWorkspace: async (id, ackVersion) => {
    await deleteWorkspaceRequest(id, ackVersion)
    set((state) => ({
      workspaces: state.workspaces.filter((w) => w.id !== id),
      currentWorkspace:
        state.currentWorkspace?.id === id ? null : state.currentWorkspace,
    }))
    // Refresh the trash list so the "Recently deleted" section reflects the move.
    try {
      const trashedWorkspaces = await listTrashedWorkspaces()
      set({ trashedWorkspaces })
    } catch {
      // The delete already succeeded; a trash-refresh blip is non-fatal.
    }
  },

  restoreWorkspace: async (id) => {
    const restored = await restoreWorkspaceRequest(id)
    set((state) => ({
      trashedWorkspaces: state.trashedWorkspaces.filter((w) => w.id !== id),
      workspaces: [
        restored,
        ...state.workspaces.filter((w) => w.id !== restored.id),
      ],
    }))
  },
}))

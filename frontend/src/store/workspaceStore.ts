import { create } from "zustand"
import {
  createWorkspace,
  deleteWorkspace as deleteWorkspaceRequest,
  getWorkspace,
  getWorkspaces,
} from "../services/api"
import type { CreateWorkspacePayload, Workspace, WorkspaceWithStages } from "../types/workspace"

interface WorkspaceState {
  workspaces: Workspace[]
  currentWorkspace: WorkspaceWithStages | null
  isLoading: boolean
  fetchWorkspaces: () => Promise<void>
  fetchWorkspace: (id: string) => Promise<void>
  setCurrentWorkspace: (workspace: WorkspaceWithStages | null) => void
  createWorkspace: (payload: CreateWorkspacePayload) => Promise<WorkspaceWithStages>
  deleteWorkspace: (id: string) => Promise<void>
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  workspaces: [],
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

  deleteWorkspace: async (id) => {
    await deleteWorkspaceRequest(id)
    set((state) => ({
      workspaces: state.workspaces.filter((w) => w.id !== id),
      currentWorkspace:
        state.currentWorkspace?.id === id ? null : state.currentWorkspace,
    }))
  },
}))

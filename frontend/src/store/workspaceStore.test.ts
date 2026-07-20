import { beforeEach, describe, expect, it, vi } from "vitest"
import type { TrashedWorkspace } from "../types/retention"
import type { WorkspaceWithStages } from "../types/workspace"

const api = vi.hoisted(() => ({
  createWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
  getWorkspace: vi.fn(),
  getWorkspaces: vi.fn(),
  listTrashedWorkspaces: vi.fn(),
  restoreWorkspace: vi.fn(),
}))

vi.mock("../services/api", () => api)

import { useWorkspaceStore } from "./workspaceStore"

function workspace(id: string, name = id): WorkspaceWithStages {
  return {
    id,
    user_id: "user-1",
    name,
    problem_statement: "Build a reliable product",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    stages: [],
  }
}

function trashed(id: string): TrashedWorkspace {
  return {
    id,
    name: id,
    archived_at: "2026-01-01T00:00:00Z",
    purge_after: "2026-02-01T00:00:00Z",
    acknowledged: true,
  }
}

describe("useWorkspaceStore", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    useWorkspaceStore.setState({
      workspaces: [],
      trashedWorkspaces: [],
      currentWorkspace: null,
      isLoading: false,
    })
  })

  it("loads workspace lists and always settles loading state", async () => {
    api.getWorkspaces.mockResolvedValue([workspace("one")])
    await useWorkspaceStore.getState().fetchWorkspaces()
    expect(useWorkspaceStore.getState()).toMatchObject({
      workspaces: [expect.objectContaining({ id: "one" })],
      isLoading: false,
    })

    api.getWorkspaces.mockRejectedValue(new Error("offline"))
    await useWorkspaceStore.getState().fetchWorkspaces()
    expect(useWorkspaceStore.getState().isLoading).toBe(false)
  })

  it("loads one workspace without erasing the last good value on failure", async () => {
    const previous = workspace("previous")
    useWorkspaceStore.setState({ currentWorkspace: previous })
    api.getWorkspace.mockResolvedValue(workspace("next"))
    await useWorkspaceStore.getState().fetchWorkspace("next")
    expect(useWorkspaceStore.getState().currentWorkspace?.id).toBe("next")

    api.getWorkspace.mockRejectedValue(new Error("timeout"))
    await useWorkspaceStore.getState().fetchWorkspace("missing")
    expect(useWorkspaceStore.getState()).toMatchObject({
      currentWorkspace: expect.objectContaining({ id: "next" }),
      isLoading: false,
    })
  })

  it("treats trash discovery as best-effort", async () => {
    api.listTrashedWorkspaces.mockResolvedValue([trashed("old")])
    await useWorkspaceStore.getState().fetchTrashed()
    expect(useWorkspaceStore.getState().trashedWorkspaces).toHaveLength(1)

    api.listTrashedWorkspaces.mockRejectedValue(new Error("offline"))
    await useWorkspaceStore.getState().fetchTrashed()
    expect(useWorkspaceStore.getState().trashedWorkspaces).toEqual([])
  })

  it("prepends a created workspace only after the server succeeds", async () => {
    useWorkspaceStore.setState({ workspaces: [workspace("existing")] })
    api.createWorkspace.mockResolvedValue(workspace("created"))
    await expect(
      useWorkspaceStore.getState().createWorkspace({
        name: "created",
        problem_statement: "A sufficiently specific problem statement",
      }),
    ).resolves.toMatchObject({ id: "created" })
    expect(useWorkspaceStore.getState().workspaces.map(({ id }) => id)).toEqual([
      "created",
      "existing",
    ])
  })

  it("removes a deleted current workspace and refreshes trash", async () => {
    const removed = workspace("removed")
    useWorkspaceStore.setState({
      workspaces: [removed, workspace("kept")],
      currentWorkspace: removed,
    })
    api.deleteWorkspace.mockResolvedValue(undefined)
    api.listTrashedWorkspaces.mockResolvedValue([trashed("removed")])

    await useWorkspaceStore.getState().deleteWorkspace("removed", "v1")

    expect(api.deleteWorkspace).toHaveBeenCalledWith("removed", "v1")
    expect(useWorkspaceStore.getState()).toMatchObject({
      workspaces: [expect.objectContaining({ id: "kept" })],
      currentWorkspace: null,
      trashedWorkspaces: [expect.objectContaining({ id: "removed" })],
    })
  })

  it("keeps a successful delete when the follow-up trash refresh fails", async () => {
    useWorkspaceStore.setState({
      workspaces: [workspace("removed"), workspace("kept")],
      currentWorkspace: workspace("kept"),
      trashedWorkspaces: [trashed("prior")],
    })
    api.deleteWorkspace.mockResolvedValue(undefined)
    api.listTrashedWorkspaces.mockRejectedValue(new Error("offline"))

    await useWorkspaceStore.getState().deleteWorkspace("removed")

    expect(useWorkspaceStore.getState().workspaces.map(({ id }) => id)).toEqual(["kept"])
    expect(useWorkspaceStore.getState().currentWorkspace?.id).toBe("kept")
    expect(useWorkspaceStore.getState().trashedWorkspaces[0].id).toBe("prior")
  })

  it("restores without duplicating an existing live entry", async () => {
    useWorkspaceStore.setState({
      workspaces: [workspace("restored", "stale"), workspace("kept")],
      trashedWorkspaces: [trashed("restored"), trashed("other")],
    })
    api.restoreWorkspace.mockResolvedValue(workspace("restored", "fresh"))

    await useWorkspaceStore.getState().restoreWorkspace("restored")

    expect(useWorkspaceStore.getState().workspaces.map(({ id }) => id)).toEqual([
      "restored",
      "kept",
    ])
    expect(useWorkspaceStore.getState().workspaces[0].name).toBe("fresh")
    expect(useWorkspaceStore.getState().trashedWorkspaces.map(({ id }) => id)).toEqual([
      "other",
    ])
  })

  it("supports explicitly clearing the selected workspace", () => {
    useWorkspaceStore.getState().setCurrentWorkspace(workspace("selected"))
    expect(useWorkspaceStore.getState().currentWorkspace?.id).toBe("selected")
    useWorkspaceStore.getState().setCurrentWorkspace(null)
    expect(useWorkspaceStore.getState().currentWorkspace).toBeNull()
  })
})

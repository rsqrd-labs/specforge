import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { GitHubSyncState } from "../hooks/useGitHubSync"
import type { SyncState } from "../types/github"

const api = vi.hoisted(() => ({
  getGitHubPush: vi.fn(),
  getWorkspace: vi.fn(),
  listIncrements: vi.fn(),
}))
const useGitHubSync = vi.hoisted(() => vi.fn())

vi.mock("../services/api", () => api)
vi.mock("../hooks/useGitHubSync", () => ({ useGitHubSync }))

import WorkspaceGitHub from "./WorkspaceGitHub"

function syncData(overrides: Partial<SyncState> = {}): SyncState {
  return {
    push_id: "push-1",
    status: "completed",
    task_sync_status: "up_to_date",
    sync_paused: false,
    out_of_sync: false,
    shipped: 1,
    total: 2,
    last_inbound_sync_at: "2026-01-02T00:00:00Z",
    last_inbound_sync_error: null,
    tasks: [
      {
        task_ref: "task-done",
        issue_number: 12,
        state: "done",
        done_via: "pr_merge",
        done_at: "2026-01-02T00:00:00Z",
        synced_at: "2026-01-02T00:00:00Z",
        human_ref: "T-012",
        title: "Ship the audit feed",
      },
      {
        task_ref: "task-open",
        issue_number: 13,
        state: "open",
        done_via: null,
        done_at: null,
        synced_at: null,
        human_ref: null,
        title: null,
      },
    ],
    ...overrides,
  }
}

function syncState(overrides: Partial<GitHubSyncState> = {}): GitHubSyncState {
  return {
    data: syncData(),
    repoFullName: "team/reliable-launch",
    repoUrl: "https://github.com/team/reliable-launch/",
    connection: "connected",
    loading: false,
    resyncing: false,
    resync: vi.fn().mockResolvedValue(undefined),
    refreshing: false,
    refreshError: null,
    refreshFromGitHub: vi.fn().mockResolvedValue(true),
    ...overrides,
  }
}

function renderPage(path = "/workspace/workspace-1/github") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/workspace/:id/github" element={<WorkspaceGitHub />} />
        <Route path="/dashboard" element={<div>Dashboard destination</div>} />
        <Route path="/workspace/:id" element={<div>Workspace destination</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe("WorkspaceGitHub", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    api.getGitHubPush.mockResolvedValue({
      push_id: "push-1",
      status: "completed",
      repo_full_name: "team/reliable-launch",
      repo_url: "https://github.com/team/reliable-launch",
      issue_count: 2,
      installation_id: "installation-1",
      pushed_at: "2026-01-01T00:00:00Z",
    })
    api.listIncrements.mockResolvedValue([
      {
        id: "baseline",
        sequence: 0,
        title: "Initial export",
        status: "pushed",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "increment",
        sequence: 1,
        title: "Audit feed",
        status: "ready",
        created_at: "2026-01-02T00:00:00Z",
        updated_at: "2026-01-02T00:00:00Z",
      },
    ])
    api.getWorkspace.mockResolvedValue({ name: "Reliable Launch" })
    useGitHubSync.mockReturnValue(syncState())
  })

  it("renders repository progress, human task identity, issue links, and increments", async () => {
    renderPage()
    expect(await screen.findByRole("heading", { name: /team\/reliable-launch/i })).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "1 of 2 tasks shipped" })).toBeInTheDocument()
    expect(screen.getByText("Ship the audit feed")).toBeInTheDocument()
    expect(screen.getByText("Issue #13")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Issue #12 ↗" })).toHaveAttribute(
      "href",
      "https://github.com/team/reliable-launch/issues/12",
    )
    expect(screen.getByRole("region", { name: "Increment timeline" })).toHaveTextContent(
      "Increment 1 · Audit feed",
    )
  })

  it("reports successful and failed user-triggered sync actions", async () => {
    const state = syncState()
    useGitHubSync.mockReturnValue(state)
    renderPage()
    await screen.findByText("Ship the audit feed")

    fireEvent.click(screen.getByRole("button", { name: "Push task changes" }))
    await waitFor(() => expect(state.resync).toHaveBeenCalled())
    expect(screen.getByRole("status")).toHaveTextContent("Re-sync started")

    vi.mocked(state.refreshFromGitHub).mockResolvedValueOnce(false)
    fireEvent.click(screen.getByRole("button", { name: "Check now" }))
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("taking longer than expected"),
    )
  })

  it("shows drift and disables actions when the installation is disconnected", async () => {
    useGitHubSync.mockReturnValue(
      syncState({
        data: syncData({ task_sync_status: "changes_pending", out_of_sync: true }),
        connection: "disconnected",
      }),
    )
    renderPage()
    expect(await screen.findByText(/Sync paused —/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Reconnect" })).toHaveAttribute(
      "href",
      "/settings",
    )
    expect(screen.getByRole("button", { name: "Push task changes" })).toBeDisabled()
    expect(screen.getByText("Reconnect GitHub to resume")).toBeInTheDocument()
  })

  it("renders the normal not-exported state when metadata endpoints fail", async () => {
    useGitHubSync.mockReturnValue(syncState({ data: null }))
    api.getGitHubPush.mockRejectedValue(new Error("not found"))
    api.listIncrements.mockRejectedValue(new Error("not found"))
    api.getWorkspace.mockRejectedValue(new Error("offline"))
    renderPage()
    expect(await screen.findByRole("heading", { name: "Not exported yet" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Open workspace" }))
    expect(screen.getByText("Workspace destination")).toBeInTheDocument()
  })
})

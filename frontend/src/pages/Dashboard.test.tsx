import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { Stage } from "../types/stage"
import type { WorkspaceWithStages } from "../types/workspace"

const api = vi.hoisted(() => ({
  createWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
  fetchBillingHistory: vi.fn(),
  getApiErrorMessage: vi.fn((_error: unknown, fallback: string) => fallback),
  getCredits: vi.fn(),
  getGitHubIntegration: vi.fn(),
  getRetentionPolicy: vi.fn(),
  getTemplates: vi.fn(),
  getWorkspaces: vi.fn(),
  listTrashedWorkspaces: vi.fn(),
  logout: vi.fn(),
  restoreWorkspace: vi.fn(),
}))

vi.mock("../services/api", () => api)

import Dashboard from "./Dashboard"
import { useUserStore } from "../store/userStore"
import { useWorkspaceStore } from "../store/workspaceStore"

function stage(type: Stage["type"], status: Stage["status"]): Stage {
  return {
    id: `${type}-stage`,
    workspace_id: "workspace-1",
    type,
    content: "content",
    status,
    current_version: 1,
    finalised_at: status === "finalised" ? "2026-01-01T00:00:00Z" : null,
    review_gate_acknowledged: false,
    gap_patch_used: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  }
}

function workspace(stages: Stage[] = []): WorkspaceWithStages {
  return {
    id: "workspace-1",
    user_id: "user-1",
    name: "Reliable Launch",
    problem_statement: "Help teams ship reliable launches",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    stages,
  }
}

function renderDashboard() {
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  )
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    api.getCredits.mockResolvedValue({ balance: 75, generation_cost: 10 })
    api.getGitHubIntegration.mockResolvedValue({
      connected: false,
      github_username: null,
    })
    api.fetchBillingHistory.mockResolvedValue([])
    api.getRetentionPolicy.mockResolvedValue({
      policy_version: "retention-v1",
      trash_days: 30,
      legacy_archived_days: 90,
      stage_versions_keep: 20,
      stage_versions_min_age_days: 30,
      storyboards_keep: 10,
      storyboards_min_age_days: 30,
      cost_events_days: 90,
      eval_results_days: 90,
    })
    api.getTemplates.mockResolvedValue([])
    api.listTrashedWorkspaces.mockResolvedValue([])
    api.deleteWorkspace.mockResolvedValue(undefined)
    api.restoreWorkspace.mockResolvedValue(workspace())
    useUserStore.setState({
      user: {
        id: "user-1",
        email: "owner@example.com",
        google_id: "google-1",
        name: "Ada Lovelace",
        avatar_url: null,
        credit_balance: 75,
        created_at: "2026-01-01T00:00:00Z",
      },
      isLoading: false,
    })
    useWorkspaceStore.setState({
      workspaces: [],
      trashedWorkspaces: [],
      currentWorkspace: null,
      isLoading: false,
    })
  })

  it("renders the empty launch path and opens contextual creation choices", async () => {
    api.getWorkspaces.mockResolvedValue([])
    renderDashboard()

    expect(await screen.findByText("Your first great brief starts here")).toBeInTheDocument()
    const spec = screen.getByRole("button", { name: /Spec Turn the spark/i })
    fireEvent.click(spec)
    expect(screen.getByRole("status")).toHaveTextContent("What is a spec?")
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByRole("status")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /Draft the first workspace/i }))
    expect(screen.getByRole("dialog")).toBeInTheDocument()
  })

  it("summarises a live pipeline and completes the confirmed trash transition", async () => {
    api.getWorkspaces.mockResolvedValue([
      workspace([
        stage("spec", "finalised"),
        stage("plan", "finalised"),
        stage("harness", "stale"),
        stage("tasks", "locked"),
      ]),
    ])
    renderDashboard()

    expect(await screen.findAllByText("Reliable Launch")).toHaveLength(2)
    expect(screen.getByText("Harness needs refresh. Last touched Jan 2.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Refresh Harness" })).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole("button", { name: "Move Reliable Launch to trash" }),
    )
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /Move to trash/i }))

    await waitFor(() =>
      expect(api.deleteWorkspace).toHaveBeenCalledWith("workspace-1", "retention-v1"),
    )
    await waitFor(() => expect(screen.queryAllByText("Reliable Launch")).toHaveLength(0))
  })

  it("surfaces partial summary failures and retries without hiding workspaces", async () => {
    api.getWorkspaces.mockResolvedValue([workspace([stage("tasks", "finalised")])])
    api.getCredits.mockRejectedValueOnce(new Error("credits offline"))
    api.fetchBillingHistory.mockRejectedValueOnce(new Error("history offline"))
    renderDashboard()

    expect(await screen.findByText("Dashboard data is partially unavailable")).toBeInTheDocument()
    expect(screen.getAllByText("Reliable Launch")).toHaveLength(2)
    api.getCredits.mockResolvedValue({ balance: 50, generation_cost: 10 })
    api.fetchBillingHistory.mockResolvedValue([])
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    await waitFor(() => expect(api.getCredits).toHaveBeenCalledTimes(2))
  })

  it("clears local identity even when server logout is unavailable", async () => {
    api.getWorkspaces.mockResolvedValue([])
    api.logout.mockRejectedValue(new Error("session already gone"))
    renderDashboard()
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }))
    await waitFor(() => expect(useUserStore.getState().user).toBeNull())
  })
})

import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { listGitHubExports } from "../services/api"
import type { ExportSummary } from "../types/github"
import GitHubHub from "./GitHubHub"

vi.mock("../services/api", () => ({
  listGitHubExports: vi.fn(),
  getApiErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

const listGitHubExportsMock = vi.mocked(listGitHubExports)

function row(overrides: Partial<ExportSummary> = {}): ExportSummary {
  return {
    workspace_id: "11111111-1111-4111-8111-111111111111",
    workspace_name: "Atlas launch",
    push_id: "22222222-2222-4222-8222-222222222222",
    status: "completed",
    export_mode: "files_to_default",
    repo_full_name: "acme/atlas",
    repo_url: "https://github.com/acme/atlas",
    pr_number: null,
    task_sync_status: "up_to_date",
    sync_paused: false,
    out_of_sync: false,
    shipped: 3,
    total: 5,
    pushed_at: "2026-07-17T10:00:00Z",
    last_inbound_sync_at: "2026-07-18T10:00:00Z",
    ...overrides,
  }
}

function renderHub() {
  return render(
    <MemoryRouter initialEntries={["/github"]}>
      <GitHubHub />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  listGitHubExportsMock.mockReset()
  listGitHubExportsMock.mockResolvedValue([
    row(),
    row({
      workspace_id: "33333333-3333-4333-8333-333333333333",
      workspace_name: "Beacon API",
      push_id: "44444444-4444-4444-8444-444444444444",
      repo_full_name: "acme/beacon",
      repo_url: "javascript:alert(1)",
      task_sync_status: "changes_pending",
      out_of_sync: true,
      shipped: 1,
      total: 6,
    }),
  ])
})

describe("GitHubHub", () => {
  it("renders accurate status language, activity, and safe repository actions", async () => {
    renderHub()

    expect(await screen.findByText("Atlas launch")).toBeInTheDocument()
    expect(screen.getByText("In sync")).toBeInTheDocument()
    expect(screen.getAllByText(/^Synced /)).toHaveLength(2)
    expect(screen.getByText("3/5 shipped")).toBeInTheDocument()

    const detailLink = screen.getByRole("link", {
      name: "View Atlas launch GitHub export details",
    })
    expect(detailLink).toHaveAttribute(
      "href",
      "/workspace/11111111-1111-4111-8111-111111111111/github",
    )

    const externalLink = screen.getByRole("link", {
      name: "Open acme/atlas on GitHub in a new tab",
    })
    expect(externalLink).toHaveAttribute("href", "https://github.com/acme/atlas")
    expect(externalLink).toHaveAttribute("target", "_blank")
    expect(externalLink).toHaveAttribute("rel", "noopener noreferrer")
    expect(
      screen.queryByRole("link", {
        name: "Open acme/beacon on GitHub in a new tab",
      }),
    ).not.toBeInTheDocument()
  })

  it("filters by attention and searches across repository names", async () => {
    const user = userEvent.setup()
    renderHub()
    await screen.findByText("Atlas launch")

    await user.click(screen.getByRole("button", { name: /Attention 1/ }))
    expect(screen.queryByText("Atlas launch")).not.toBeInTheDocument()
    expect(screen.getByText("Beacon API")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /All 2/ }))
    await user.type(
      screen.getByRole("searchbox", { name: "Search repositories" }),
      "acme/atlas",
    )
    expect(screen.getByText("Atlas launch")).toBeInTheDocument()
    expect(screen.queryByText("Beacon API")).not.toBeInTheDocument()
  })

  it("refreshes in place without discarding the current rows", async () => {
    const user = userEvent.setup()
    renderHub()
    await screen.findByText("Atlas launch")

    listGitHubExportsMock.mockResolvedValueOnce([
      row({ workspace_name: "Atlas launch v2" }),
    ])
    await user.click(screen.getByRole("button", { name: "Refresh repositories" }))

    await waitFor(() => expect(listGitHubExportsMock).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("Atlas launch v2")).toBeInTheDocument()
    expect(screen.queryByText("Atlas launch")).not.toBeInTheDocument()
  })
})

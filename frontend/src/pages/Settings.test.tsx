import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router"

import { AI_DISCLAIMER_COPY } from "../components/shared/AiDisclaimer"
import { getGitHubIntegration, getRetentionPolicy } from "../services/api"
import Settings from "./Settings"

vi.mock("../components/settings/GitHubConnection", () => ({
  default: () => <div>GitHub connection panel</div>,
}))

vi.mock("../services/api", () => ({
  getGitHubIntegration: vi.fn().mockResolvedValue(null),
  // Settings now renders <DataRetentionPanel/>, which fetches the policy.
  getRetentionPolicy: vi.fn().mockResolvedValue({
    policy_version: "trash-v1",
    trash_days: 30,
    legacy_archived_days: 180,
    stage_versions_keep: 20,
    stage_versions_min_age_days: 90,
    storyboards_keep: 5,
    storyboards_min_age_days: 90,
    cost_events_days: 180,
    eval_results_days: 180,
  }),
}))

function renderSettings(
  entry: string | { pathname: string; state?: unknown } = "/settings",
) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/settings" element={<Settings />} />
        <Route path="/workspace/:id" element={<div>Workspace destination</div>} />
        <Route path="/dashboard" element={<div>Dashboard destination</div>} />
        <Route path="/github" element={<div>GitHub destination</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
})

describe("Settings", () => {
  it("renders the AI disclosure below the settings content", () => {
    renderSettings()

    expect(screen.getByText("GitHub connection panel")).toBeInTheDocument()
    expect(screen.getByText(AI_DISCLAIMER_COPY)).toBeInTheDocument()
    expect(getGitHubIntegration).toHaveBeenCalledOnce()
  })

  it("returns to the originating workspace and clears the stored destination", () => {
    renderSettings({ pathname: "/settings", state: { from: "/workspace/ws-1" } })
    expect(sessionStorage.getItem("thought2build:settings_return_to")).toBe("/workspace/ws-1")
    fireEvent.click(screen.getByRole("button", { name: "Back to Workspace" }))
    expect(screen.getByText("Workspace destination")).toBeInTheDocument()
    expect(sessionStorage.getItem("thought2build:settings_return_to")).toBeNull()
  })

  it("ignores a self-referential origin and uses the persisted fallback", () => {
    sessionStorage.setItem("thought2build:settings_return_to", "/github")
    renderSettings({ pathname: "/settings", state: { from: "/settings" } })
    fireEvent.click(screen.getByRole("button", { name: "Back to Back" }))
    expect(screen.getByText("GitHub destination")).toBeInTheDocument()
  })

  it("fails open when integration and retention summaries are unavailable", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined)
    vi.mocked(getGitHubIntegration).mockRejectedValueOnce(new Error("offline"))
    vi.mocked(getRetentionPolicy).mockRejectedValueOnce(new Error("offline"))
    renderSettings()
    expect(await screen.findByText("Retention details are unavailable right now.")).toBeInTheDocument()
    expect(consoleError).toHaveBeenCalledWith(
      "[Settings] failed to load GitHub integration status:",
      expect.any(Error),
    )
    consoleError.mockRestore()
  })

  it("keeps the retention panel in a stable skeleton until policy data arrives", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof getRetentionPolicy>>) => void
    vi.mocked(getRetentionPolicy).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const { container } = renderSettings()
    expect(container.querySelector(".data-retention-skeleton")).not.toBeNull()

    resolve({
      policy_version: "trash-v2",
      trash_days: 14,
      legacy_archived_days: 180,
      stage_versions_keep: 20,
      stage_versions_min_age_days: 90,
      storyboards_keep: 5,
      storyboards_min_age_days: 90,
      cost_events_days: 180,
      eval_results_days: 180,
    })
    expect(await screen.findByText("14")).toBeInTheDocument()
  })
})

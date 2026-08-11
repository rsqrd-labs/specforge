import { act, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { getGitHubIntegration } from "../../services/api"
import { GitHubStatusPill } from "./GitHubStatusPill"

vi.mock("../../services/api", () => ({ getGitHubIntegration: vi.fn() }))

const mockGetIntegration = vi.mocked(getGitHubIntegration)

function SettingsProbe() {
  const location = useLocation()
  return <div>Settings from {(location.state as { from?: string } | null)?.from ?? "unknown"}</div>
}

function renderPill() {
  return render(
    <MemoryRouter initialEntries={["/workspace/ws-1"]}>
      <Routes>
        <Route path="/workspace/:id" element={<GitHubStatusPill />} />
        <Route path="/settings" element={<SettingsProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe("GitHubStatusPill", () => {
  beforeEach(() => mockGetIntegration.mockReset())

  it("renders a connected username and preserves the originating route", async () => {
    mockGetIntegration.mockResolvedValue({ connected: true, github_username: "octocat" })
    renderPill()
    const link = await screen.findByRole("link", {
      name: "GitHub connected as @octocat. Manage in Settings.",
    })
    expect(link).toHaveClass("connected")
    expect(link).toHaveAttribute("title", "Manage GitHub connection")
    expect(screen.getByText("@octocat")).toBeInTheDocument()
    link.click()
    expect(await screen.findByText("Settings from /workspace/ws-1")).toBeInTheDocument()
  })

  it("uses safe connected fallbacks when GitHub omits the username", async () => {
    mockGetIntegration.mockResolvedValue({ connected: true, github_username: null })
    renderPill()
    expect(await screen.findByText("@github-user")).toBeInTheDocument()
    expect(screen.getByRole("link")).toHaveAccessibleName(
      "GitHub connected as @user. Manage in Settings.",
    )
  })

  it("renders the explicit disconnected result as a settings recovery link", async () => {
    mockGetIntegration.mockResolvedValue({ connected: false, github_username: null })
    renderPill()
    const link = await screen.findByRole("link", { name: "Connect GitHub in Settings" })
    expect(link).toHaveClass("not-connected")
    expect(link).toHaveAttribute("title", "Connect GitHub")
  })

  it("ignores both a late success and a late failure after unmount", async () => {
    let resolve!: (value: { connected: boolean; github_username: string | null }) => void
    mockGetIntegration.mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const successView = renderPill()
    successView.unmount()
    await act(async () => resolve({ connected: true, github_username: "late" }))

    let reject!: (reason: unknown) => void
    mockGetIntegration.mockReturnValueOnce(new Promise((_done, fail) => { reject = fail }))
    const failureView = renderPill()
    failureView.unmount()
    await act(async () => reject(new Error("late failure")))
    expect(screen.queryByText("@late")).toBeNull()
  })
})

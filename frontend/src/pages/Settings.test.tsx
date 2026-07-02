import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import { AI_DISCLAIMER_COPY } from "../components/shared/AiDisclaimer"
import { getGitHubIntegration } from "../services/api"
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

function renderSettings() {
  return render(
    <MemoryRouter initialEntries={["/settings"]}>
      <Settings />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.clearAllMocks()
})

describe("Settings", () => {
  it("renders the AI disclosure below the settings content", () => {
    renderSettings()

    expect(screen.getByText("GitHub connection panel")).toBeInTheDocument()
    expect(screen.getByText(AI_DISCLAIMER_COPY)).toBeInTheDocument()
    expect(getGitHubIntegration).toHaveBeenCalledOnce()
  })
})

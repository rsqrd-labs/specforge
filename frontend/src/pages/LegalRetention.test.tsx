import { act, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router"

import { getRetentionPolicy } from "../services/api"
import type { RetentionPolicy } from "../types/retention"
import LegalRetention from "./LegalRetention"

vi.mock("../services/api", () => ({
  getRetentionPolicy: vi.fn(),
}))

const POLICY: RetentionPolicy = {
  policy_version: "trash-v1",
  trash_days: 30,
  legacy_archived_days: 180,
  stage_versions_keep: 20,
  stage_versions_min_age_days: 90,
  storyboards_keep: 5,
  storyboards_min_age_days: 90,
  cost_events_days: 180,
  eval_results_days: 180,
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/legal/retention"]}>
      <Routes>
        <Route path="/legal/retention" element={<LegalRetention />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(getRetentionPolicy).mockResolvedValue(POLICY)
})

describe("LegalRetention", () => {
  it("renders the full policy with the live windows", async () => {
    renderPage()

    expect(
      screen.getByRole("heading", { name: "Data Retention Policy" }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/Policy version: trash-v1/)).toBeInTheDocument()

    // The interpolated windows from GET /retention/policy. "180 days" appears
    // in both the legacy-window and telemetry sections, hence getAllByText.
    expect(screen.getByText(/30 days/)).toBeInTheDocument()
    expect(screen.getAllByText(/180 days/).length).toBeGreaterThan(0)

    // Every policy section renders (the page is the published legal document —
    // a missing section is a policy change, not a styling tweak).
    for (const section of [
      /trash, then permanent deletion/i,
      /version and keynote history/i,
      /internal telemetry/i,
      /what is kept indefinitely/i,
      /your controls/i,
      /account deletion and data-subject requests/i,
    ]) {
      expect(screen.getByRole("heading", { name: section })).toBeInTheDocument()
    }
  })

  it("still renders the complete policy when the policy endpoint fails", async () => {
    vi.mocked(getRetentionPolicy).mockRejectedValue(new Error("network down"))

    renderPage()

    // The config-default copy renders — a legal page must never be empty.
    expect(
      screen.getByRole("heading", { name: "Data Retention Policy" }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/Policy version: trash-v1/)).toBeInTheDocument()
    expect(screen.getByText(/30 days/)).toBeInTheDocument()
    expect(
      screen.getByRole("heading", { name: /internal telemetry/i }),
    ).toBeInTheDocument()
  })

  it("links back to the app root", () => {
    renderPage()
    expect(screen.getByRole("link", { name: /back to thought2build/i })).toHaveAttribute(
      "href",
      "/",
    )
  })

  it("ignores policy data that arrives after the legal page unmounts", async () => {
    let resolve!: (value: RetentionPolicy) => void
    vi.mocked(getRetentionPolicy).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const view = renderPage()
    view.unmount()
    await act(async () => resolve({ ...POLICY, policy_version: "late-policy" }))
    expect(document.body).not.toHaveTextContent("late-policy")
  })
})

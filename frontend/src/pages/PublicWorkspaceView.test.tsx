import { render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import { AI_DISCLAIMER_COPY } from "../components/shared/AiDisclaimer"
import { getPublicWorkspace } from "../services/api"
import type { PublicWorkspaceResponse } from "../types/publicShare"
import PublicWorkspaceView from "./PublicWorkspaceView"

vi.mock("../services/api", () => ({
  getPublicWorkspace: vi.fn(),
}))

const PUBLIC_WORKSPACE: PublicWorkspaceResponse = {
  name: "Shared Spec",
  stages: [
    { type: "spec", content: "# Spec\n\nGenerated requirements." },
    { type: "plan", content: "# Plan" },
    { type: "harness", content: "# Harness" },
    { type: "tasks", content: "# Tasks" },
  ],
  coverage_summary: null,
  eval_summary: null,
  shared_at: "2026-06-01T00:00:00Z",
}

function renderPublicWorkspace(path = "/p/shared123") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/p/:slug" element={<PublicWorkspaceView />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(getPublicWorkspace).mockResolvedValue(PUBLIC_WORKSPACE)
})

afterEach(() => {
  document.head
    .querySelectorAll("#specforge-public-noindex")
    .forEach((node) => node.remove())
  vi.clearAllMocks()
})

describe("PublicWorkspaceView", () => {
  it("renders the AI disclosure in the public footer", async () => {
    renderPublicWorkspace()

    expect(await screen.findByRole("heading", { name: /shared spec/i })).toBeInTheDocument()
    expect(screen.getByText(AI_DISCLAIMER_COPY)).toBeInTheDocument()
  })
})

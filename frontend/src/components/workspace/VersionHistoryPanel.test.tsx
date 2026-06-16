import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { VersionHistoryPanel } from "./VersionHistoryPanel"
import { getStageVersions } from "../../services/api"
import type { Stage, StageVersion } from "../../types/stage"

vi.mock("../../services/api", () => ({
  getStageVersions: vi.fn(),
}))

const mockGet = vi.mocked(getStageVersions)

afterEach(() => {
  vi.clearAllMocks()
})

const stage = {
  id: "stage-1",
  type: "spec",
  status: "draft",
  current_version: 2,
} as unknown as Stage

function version(over: Partial<StageVersion>): StageVersion {
  return {
    id: over.id ?? "v",
    stage_id: "stage-1",
    version: over.version ?? 1,
    content: "x",
    created_by: "ai",
    created_at: "2026-06-17T10:00:00Z",
    ...over,
  }
}

describe("VersionHistoryPanel research provenance (issue #12, Phase 4)", () => {
  it("shows a research badge + source links only on grounded versions", async () => {
    mockGet.mockResolvedValue([
      version({ id: "v1", version: 1 }),
      version({
        id: "v2",
        version: 2,
        research_context: "## External Research Context\n…",
        research_sources: [
          { url: "https://fastapi.tiangolo.com/release", title: "FastAPI" },
        ],
      }),
    ])

    render(<VersionHistoryPanel stage={stage} onRollback={vi.fn()} />)

    await waitFor(() =>
      expect(screen.getByText(/grounded with web research/i)).toBeInTheDocument(),
    )
    // Exactly one badge — only the grounded version carries it.
    expect(screen.getAllByText(/grounded with web research/i)).toHaveLength(1)
    const link = screen.getByRole("link", { name: "fastapi.tiangolo.com" })
    expect(link).toHaveAttribute("href", "https://fastapi.tiangolo.com/release")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
  })

  it("shows provenance for a grounded FIRST generation (single version)", async () => {
    const singleStage = { ...stage, current_version: 1 } as Stage
    mockGet.mockResolvedValue([
      version({
        id: "v1",
        version: 1,
        research_context: "## External Research Context\n…",
        research_sources: [{ url: "https://pytest.org/changelog", title: "pytest" }],
      }),
    ])

    render(<VersionHistoryPanel stage={singleStage} onRollback={vi.fn()} />)

    await waitFor(() =>
      expect(screen.getByText(/grounded with web research/i)).toBeInTheDocument(),
    )
    expect(screen.getByRole("link", { name: "pytest.org" })).toBeInTheDocument()
    // No restore UI with a single version.
    expect(screen.queryByRole("button", { name: /restore/i })).not.toBeInTheDocument()
  })

  it("renders nothing for a single, ungrounded version", async () => {
    const singleStage = { ...stage, current_version: 1 } as Stage
    mockGet.mockResolvedValue([version({ id: "v1", version: 1 })])

    const { container } = render(
      <VersionHistoryPanel stage={singleStage} onRollback={vi.fn()} />,
    )
    await waitFor(() => expect(mockGet).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it("drops a non-http(s) source URL client-side (defense in depth)", async () => {
    mockGet.mockResolvedValue([
      version({ id: "v1", version: 1 }),
      version({
        id: "v2",
        version: 2,
        research_context: "block",
        research_sources: [
          { url: "javascript:alert(1)", title: "evil" },
          { url: "https://safe.example/a", title: "safe" },
        ],
      }),
    ])

    render(<VersionHistoryPanel stage={stage} onRollback={vi.fn()} />)

    await waitFor(() =>
      expect(screen.getByText(/grounded with web research/i)).toBeInTheDocument(),
    )
    expect(screen.queryByText("evil")).not.toBeInTheDocument()
    // No link points at a javascript: URL.
    for (const a of screen.getAllByRole("link")) {
      expect(a.getAttribute("href")).toMatch(/^https?:\/\//)
    }
    expect(screen.getByRole("link", { name: "safe.example" })).toBeInTheDocument()
  })
})

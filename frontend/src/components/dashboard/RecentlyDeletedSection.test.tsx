import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { RecentlyDeletedSection } from "./RecentlyDeletedSection"
import type { TrashedWorkspace } from "../../types/retention"

const restoreWorkspaceMock = vi.fn().mockResolvedValue(undefined)
const exportWorkspaceMock = vi.fn()

// A mutable fake store state the mocked selector reads from.
const storeState: {
  trashedWorkspaces: TrashedWorkspace[]
  restoreWorkspace: typeof restoreWorkspaceMock
} = {
  trashedWorkspaces: [],
  restoreWorkspace: restoreWorkspaceMock,
}

vi.mock("../../store/workspaceStore", () => ({
  useWorkspaceStore: <T,>(selector: (s: typeof storeState) => T): T =>
    selector(storeState),
}))

vi.mock("../../services/api", () => ({
  exportWorkspace: (...args: unknown[]) => exportWorkspaceMock(...args),
  getApiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

function trashed(overrides: Partial<TrashedWorkspace> = {}): TrashedWorkspace {
  const purgeAfter = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString()
  return {
    id: "ws-1",
    name: "Payments API",
    archived_at: new Date().toISOString(),
    purge_after: purgeAfter,
    acknowledged: true,
    ...overrides,
  }
}

afterEach(() => {
  storeState.trashedWorkspaces = []
  restoreWorkspaceMock.mockClear()
  exportWorkspaceMock.mockClear()
})

describe("RecentlyDeletedSection", () => {
  it("renders nothing when the trash is empty", () => {
    const { container } = render(<RecentlyDeletedSection />)
    expect(container).toBeEmptyDOMElement()
  })

  it("shows a countdown, Restore, and Export when expanded", async () => {
    storeState.trashedWorkspaces = [trashed()]
    render(<RecentlyDeletedSection />)

    await userEvent.click(
      screen.getByRole("button", { name: /recently deleted/i }),
    )

    expect(screen.getByText("Payments API")).toBeInTheDocument()
    expect(screen.getByText(/deletes in 5 days/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /restore/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /export/i })).toBeInTheDocument()
  })

  it("restores a workspace when Restore is clicked", async () => {
    storeState.trashedWorkspaces = [trashed({ id: "ws-9" })]
    render(<RecentlyDeletedSection />)

    await userEvent.click(
      screen.getByRole("button", { name: /recently deleted/i }),
    )
    await userEvent.click(screen.getByRole("button", { name: /restore/i }))

    expect(restoreWorkspaceMock).toHaveBeenCalledWith("ws-9")
  })
})

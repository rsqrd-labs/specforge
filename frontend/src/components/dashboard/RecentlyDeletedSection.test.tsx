import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
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
  vi.restoreAllMocks()
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

  it.each([
    [new Date(Date.now() - 1000).toISOString(), "Deleting soon"],
    [new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString(), "Deletes in 1 day"],
  ])("renders the boundary countdown for %s", async (purgeAfter, label) => {
    storeState.trashedWorkspaces = [trashed({ purge_after: purgeAfter })]
    render(<RecentlyDeletedSection />)
    await userEvent.click(screen.getByRole("button", { name: /recently deleted/i }))
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it("surfaces and dismisses a restore failure", async () => {
    restoreWorkspaceMock.mockRejectedValueOnce(new Error("offline"))
    storeState.trashedWorkspaces = [trashed()]
    render(<RecentlyDeletedSection />)
    await userEvent.click(screen.getByRole("button", { name: /recently deleted/i }))
    await userEvent.click(screen.getByRole("button", { name: /restore/i }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not restore this workspace")
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }))
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("exports a safe filename and revokes the object URL", async () => {
    vi.useFakeTimers()
    const blob = new Blob(["archive"])
    exportWorkspaceMock.mockResolvedValueOnce(blob)
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:archive")
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined)
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)
    storeState.trashedWorkspaces = [trashed({ name: "  !!!  ", id: "fallback-id" })]
    render(<RecentlyDeletedSection />)
    await act(async () => {
      screen.getByRole("button", { name: /recently deleted/i }).click()
    })
    await act(async () => {
      screen.getByRole("button", { name: /export/i }).click()
      await Promise.resolve()
    })
    expect(createUrl).toHaveBeenCalledWith(blob)
    expect(click).toHaveBeenCalled()
    await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
    expect(revokeUrl).toHaveBeenCalledWith("blob:archive")
    vi.useRealTimers()
  })

  it("surfaces an export failure and ignores a second action while busy", async () => {
    let reject!: (reason: unknown) => void
    exportWorkspaceMock.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
    storeState.trashedWorkspaces = [trashed()]
    render(<RecentlyDeletedSection />)
    await userEvent.click(screen.getByRole("button", { name: /recently deleted/i }))
    const exportButton = screen.getByRole("button", { name: /export/i })
    await userEvent.click(exportButton)
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "Working…" }))
    await act(async () => reject(new Error("archive failed")))
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not export this workspace"))
    expect(exportWorkspaceMock).toHaveBeenCalledTimes(1)
  })
})

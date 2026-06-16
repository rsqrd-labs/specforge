import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ResearchConsentToggle } from "./ResearchConsentToggle"
import { setWorkspaceResearch } from "../../services/api"

vi.mock("../../services/api", () => ({
  setWorkspaceResearch: vi.fn(),
}))

const mockSet = vi.mocked(setWorkspaceResearch)

afterEach(() => {
  vi.clearAllMocks()
})

function renderToggle(enabled: boolean, onChanged = vi.fn()) {
  render(
    <ResearchConsentToggle
      workspaceId="ws-1"
      enabled={enabled}
      onChanged={onChanged}
    />,
  )
  return onChanged
}

describe("ResearchConsentToggle", () => {
  it("gates opt-in behind a consent dialog naming the egress and the cost", async () => {
    const user = userEvent.setup()
    renderToggle(false)

    // Clicking an OFF switch does not toggle immediately — it asks for consent.
    await user.click(screen.getByRole("switch"))
    expect(mockSet).not.toHaveBeenCalled()

    const dialog = screen.getByRole("dialog")
    expect(dialog).toHaveTextContent(/Brave Search/i)
    expect(dialog).toHaveTextContent(/third-party/i)
    expect(dialog).toHaveTextContent(/credit/i)
  })

  it("enables research only after the user accepts consent", async () => {
    const user = userEvent.setup()
    mockSet.mockResolvedValue({ brave_research_enabled: true } as never)
    const onChanged = renderToggle(false)

    await user.click(screen.getByRole("switch"))
    await user.click(screen.getByRole("button", { name: /enable web research/i }))

    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("ws-1", true))
    expect(onChanged).toHaveBeenCalledWith(true)
  })

  it("does not enable when the user declines (Not now)", async () => {
    const user = userEvent.setup()
    const onChanged = renderToggle(false)

    await user.click(screen.getByRole("switch"))
    await user.click(screen.getByRole("button", { name: /not now/i }))

    expect(mockSet).not.toHaveBeenCalled()
    expect(onChanged).not.toHaveBeenCalled()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("opts out immediately with no dialog", async () => {
    const user = userEvent.setup()
    mockSet.mockResolvedValue({ brave_research_enabled: false } as never)
    const onChanged = renderToggle(true)

    await user.click(screen.getByRole("switch"))

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("ws-1", false))
    expect(onChanged).toHaveBeenCalledWith(false)
  })

  it("surfaces an error and stays off when the toggle fails", async () => {
    const user = userEvent.setup()
    mockSet.mockRejectedValue(new Error("boom"))
    const onChanged = renderToggle(false)

    await user.click(screen.getByRole("switch"))
    await user.click(screen.getByRole("button", { name: /enable web research/i }))

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument())
    expect(onChanged).not.toHaveBeenCalled()
  })
})

import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { StoryboardToolbar } from "./StoryboardToolbar"
import type { StoryboardSummary } from "../../types/storyboard"

function makeStoryboard(
  overrides: Partial<StoryboardSummary> = {},
): StoryboardSummary {
  return {
    id: "storyboard-1",
    workspace_id: "workspace-1",
    version: 2,
    status: "ready",
    title: "Launch Storyboard",
    theme: "Indica",
    public_share_enabled: false,
    public_share_slug: null,
    created_at: "2026-05-30T00:00:00Z",
    updated_at: "2026-05-30T00:00:00Z",
    ...overrides,
  }
}

function renderToolbar(storyboard = makeStoryboard()) {
  const handlers = {
    onOpen: vi.fn(),
    onPresent: vi.fn(),
    onShare: vi.fn(),
    onDownload: vi.fn(),
    onRegenerate: vi.fn(),
    onDownloadNotes: vi.fn(),
  }

  return {
    ...render(<StoryboardToolbar storyboard={storyboard} {...handlers} />),
    handlers,
  }
}

describe("StoryboardToolbar", () => {
  it("exposes present, share, download, regenerate, and notes actions", () => {
    renderToolbar()

    expect(screen.getByRole("button", { name: /present/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /share/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /download storyboard pdf/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /download notes/i })).toBeInTheDocument()
  })

  it("calls each ready action once", async () => {
    const user = userEvent.setup()
    const { handlers } = renderToolbar()

    await user.click(screen.getByRole("button", { name: /open storyboard/i }))
    await user.click(screen.getByRole("button", { name: /present/i }))
    await user.click(screen.getByRole("button", { name: /share/i }))
    await user.click(screen.getByRole("button", { name: /download storyboard pdf/i }))
    await user.click(screen.getByRole("button", { name: /regenerate/i }))
    await user.click(screen.getByRole("button", { name: /download notes/i }))

    expect(handlers.onOpen).toHaveBeenCalledOnce()
    expect(handlers.onPresent).toHaveBeenCalledOnce()
    expect(handlers.onShare).toHaveBeenCalledOnce()
    expect(handlers.onDownload).toHaveBeenCalledOnce()
    expect(handlers.onRegenerate).toHaveBeenCalledOnce()
    expect(handlers.onDownloadNotes).toHaveBeenCalledOnce()
  })

  it("shows stale status and keeps share disabled until the Storyboard is ready", () => {
    renderToolbar(makeStoryboard({ status: "stale" }))

    expect(screen.getByLabelText(/storyboard status stale/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /share/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeEnabled()
  })

  it("disables presentable actions while generation is running", () => {
    renderToolbar(makeStoryboard({ status: "generating" }))

    expect(screen.getByRole("button", { name: /open storyboard/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /present/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /download storyboard pdf/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /download notes/i })).toBeDisabled()
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeDisabled()
  })
})

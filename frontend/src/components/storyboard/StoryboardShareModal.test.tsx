import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  disableStoryboardShare,
  rotateStoryboardShare,
  shareStoryboard,
} from "../../services/api"
import { StoryboardShareModal } from "./StoryboardShareModal"
import { DEFAULT_TEST_PERMISSIONS } from "./testPayload"

vi.mock("../../services/api", () => ({
  shareStoryboard: vi.fn(),
  disableStoryboardShare: vi.fn(),
  rotateStoryboardShare: vi.fn(),
}))

let clipboardWrite: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.mocked(shareStoryboard).mockReset()
  vi.mocked(disableStoryboardShare).mockReset()
  vi.mocked(rotateStoryboardShare).mockReset()
  clipboardWrite = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: clipboardWrite },
  })
})

describe("StoryboardShareModal", () => {
  it("defaults private public materials to disabled and saves independent permissions", async () => {
    const user = userEvent.setup()
    vi.mocked(shareStoryboard).mockResolvedValue({
      slug: "abc123",
      url: "https://specforge.test/sb/abc123",
      enabled: true,
      permissions: DEFAULT_TEST_PERMISSIONS,
    })

    render(
      <StoryboardShareModal
        storyboardId="storyboard-1"
        initialEnabled={false}
        initialSlug={null}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByLabelText(/download the PDF/i)).toBeChecked()
    expect(screen.getByLabelText(/download speaker notes/i)).not.toBeChecked()
    expect(screen.getByLabelText(/show source evidence/i)).not.toBeChecked()
    // The technical-appendix toggle is no longer surfaced.
    expect(screen.queryByLabelText(/appendix/i)).toBeNull()

    await user.click(screen.getByRole("switch", { name: /public link/i }))

    // Every permission key — including the now-hidden appendix grant — is still
    // sent, so a previously stored value is never silently dropped.
    expect(shareStoryboard).toHaveBeenCalledWith("storyboard-1", {
      allow_pdf_download: true,
      allow_notes_download: false,
      allow_appendix_download: false,
      allow_source_layer: false,
    })
  })

  it("copies only the Storyboard /sb link and supports rotate and disable", async () => {
    const user = userEvent.setup()
    const onShareChanged = vi.fn()
    vi.mocked(rotateStoryboardShare).mockResolvedValue({
      slug: "new789",
      url: "https://specforge.test/sb/new789",
      enabled: true,
      permissions: { ...DEFAULT_TEST_PERMISSIONS, allow_source_layer: true },
    })
    vi.mocked(disableStoryboardShare).mockResolvedValue(undefined)

    render(
      <StoryboardShareModal
        storyboardId="storyboard-1"
        initialEnabled
        initialSlug="old123"
        initialPermissions={DEFAULT_TEST_PERMISSIONS}
        onClose={vi.fn()}
        onShareChanged={onShareChanged}
      />,
    )

    const shareInput = screen.getByDisplayValue(/\/sb\/old123/) as HTMLInputElement
    expect(shareInput.value).toContain("/sb/old123")
    expect(shareInput.value).not.toContain("/p/old123")
    await user.click(screen.getByRole("button", { name: /copy link/i }))
    expect(await screen.findByText(/link copied/i)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /generate new link/i }))
    await waitFor(() =>
      expect(screen.getByDisplayValue(/\/sb\/new789/)).toBeInTheDocument(),
    )
    expect(onShareChanged).toHaveBeenLastCalledWith({
      enabled: true,
      slug: "new789",
      permissions: { ...DEFAULT_TEST_PERMISSIONS, allow_source_layer: true },
    })

    await user.click(screen.getByRole("switch", { name: /public link/i }))
    expect(disableStoryboardShare).toHaveBeenCalledWith("storyboard-1")
  })
})

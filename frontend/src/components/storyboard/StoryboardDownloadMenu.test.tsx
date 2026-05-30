import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  downloadPublicStoryboard,
  downloadStoryboard,
} from "../../services/api"
import { StoryboardDownloadMenu } from "./StoryboardDownloadMenu"
import { DEFAULT_TEST_PERMISSIONS } from "./testPayload"

vi.mock("../../services/api", () => ({
  downloadStoryboard: vi.fn(),
  downloadPublicStoryboard: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(downloadStoryboard).mockReset()
  vi.mocked(downloadPublicStoryboard).mockReset()
  vi.mocked(downloadStoryboard).mockResolvedValue(undefined as unknown as Blob)
  vi.mocked(downloadPublicStoryboard).mockResolvedValue(undefined as unknown as Blob)
})

describe("StoryboardDownloadMenu", () => {
  it("exposes every owner download kind", async () => {
    const user = userEvent.setup()
    render(
      <StoryboardDownloadMenu
        mode="owner"
        title="SpecForge Launch"
        storyboardId="storyboard-1"
      />,
    )

    expect(screen.getByRole("button", { name: /HTML package/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /^PDF/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /speaker notes/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /demo script/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /technical appendix/i })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /speaker notes/i }))

    expect(downloadStoryboard).toHaveBeenCalledWith("storyboard-1", "notes", "md")
  })

  it("filters public downloads by permissions and never exposes public HTML", async () => {
    const user = userEvent.setup()
    const { rerender } = render(
      <StoryboardDownloadMenu
        mode="public"
        title="SpecForge Launch"
        slug="public123"
        permissions={DEFAULT_TEST_PERMISSIONS}
        downloads={["pdf", "notes", "demo-script", "appendix"]}
      />,
    )

    expect(screen.queryByRole("button", { name: /HTML package/i })).toBeNull()
    expect(screen.getByRole("button", { name: /^PDF/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /speaker notes/i })).toBeNull()
    expect(screen.queryByRole("button", { name: /technical appendix/i })).toBeNull()

    await user.click(screen.getByRole("button", { name: /^PDF/i }))
    expect(downloadPublicStoryboard).toHaveBeenCalledWith("public123", "pdf")

    rerender(
      <StoryboardDownloadMenu
        mode="public"
        title="SpecForge Launch"
        slug="public123"
        permissions={{
          ...DEFAULT_TEST_PERMISSIONS,
          allow_notes_download: true,
          allow_appendix_download: true,
          allow_source_layer: true,
        }}
        downloads={["pdf", "notes", "demo-script", "appendix"]}
      />,
    )

    expect(screen.getByRole("button", { name: /speaker notes/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /technical appendix/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /demo script/i })).toBeInTheDocument()
  })
})

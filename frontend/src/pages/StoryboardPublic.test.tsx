import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import StoryboardPublic from "./StoryboardPublic"
import {
  downloadPublicStoryboard,
  getPublicStoryboard,
} from "../services/api"
import {
  DEFAULT_TEST_PERMISSIONS,
  makePublicStoryboard,
} from "../components/storyboard/testPayload"

vi.mock("../services/api", () => ({
  getPublicStoryboard: vi.fn(),
  downloadPublicStoryboard: vi.fn(),
}))

function renderPublicRoute(path = "/sb/public123") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/sb/:slug" element={<StoryboardPublic />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(getPublicStoryboard).mockReset()
  vi.mocked(downloadPublicStoryboard).mockReset()
})

afterEach(() => {
  document.head
    .querySelectorAll("#specforge-storyboard-public-noindex")
    .forEach((node) => node.remove())
})

describe("StoryboardPublic", () => {
  it("renders the public launch page with noindex and no auth redirect", async () => {
    vi.mocked(getPublicStoryboard).mockResolvedValue(makePublicStoryboard())

    renderPublicRoute()

    expect(await screen.findByRole("heading", { name: /specforge launch/i })).toBeInTheDocument()
    expect(
      document.head.querySelector('meta[name="robots"]')?.getAttribute("content"),
    ).toBe("noindex, nofollow")
    expect(screen.getByRole("button", { name: /present/i })).toBeEnabled()
  })

  it("keeps public notes and source layer hidden by default", async () => {
    const user = userEvent.setup()
    vi.mocked(getPublicStoryboard).mockResolvedValue(makePublicStoryboard())

    renderPublicRoute()

    await screen.findByRole("heading", { name: /specforge launch/i })
    expect(screen.getByRole("button", { name: /speaker notes/i })).toBeDisabled()

    await user.click(screen.getByRole("button", { name: /present/i }))
    fireEvent.keyDown(window, { key: "p" })
    fireEvent.keyDown(window, { key: "s" })

    expect(screen.queryByLabelText(/presenter mode/i)).toBeNull()
    expect(screen.queryByLabelText(/source layer/i)).toBeNull()
    expect(screen.queryByText(/opening thesis talk track/i)).toBeNull()
  })

  it("reveals bounded public source excerpts only when source permission is enabled", async () => {
    const user = userEvent.setup()
    vi.mocked(getPublicStoryboard).mockResolvedValue(
      makePublicStoryboard({
        permissions: { ...DEFAULT_TEST_PERMISSIONS, allow_source_layer: true },
      }),
    )

    const { container } = renderPublicRoute()

    await user.click(await screen.findByRole("button", { name: /present/i }))
    fireEvent.keyDown(window, { key: "s" })
    await user.click(screen.getByRole("button", { name: /SPEC/i }))

    const excerpt = container.querySelector(".source-layer__excerpts p")
    expect(excerpt?.textContent?.length).toBeLessThanOrEqual(1203)
  })

  it("renders a safe empty state for disabled or rotated links", async () => {
    vi.mocked(getPublicStoryboard).mockResolvedValue(null)

    renderPublicRoute("/sb/missing")

    expect(
      await screen.findByText(/storyboard link is no longer available/i),
    ).toBeInTheDocument()
  })
})

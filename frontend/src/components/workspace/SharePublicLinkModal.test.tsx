import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { disablePublicShare, enablePublicShare, rotatePublicShare } from "../../services/api"
import { SharePublicLinkModal } from "./SharePublicLinkModal"

vi.mock("../../hooks/useFocusTrap", () => ({ useFocusTrap: vi.fn() }))
vi.mock("qrcode.react", () => ({ QRCodeSVG: ({ value }: { value: string }) => <svg aria-label={`QR ${value}`} /> }))
vi.mock("../../services/api", () => ({
  disablePublicShare: vi.fn(), enablePublicShare: vi.fn(), rotatePublicShare: vi.fn(),
  getApiErrorMessage: vi.fn((_error, fallback) => fallback),
}))

describe("SharePublicLinkModal", () => {
  const close = vi.fn()
  beforeEach(() => {
    close.mockReset()
    vi.mocked(enablePublicShare).mockReset()
    vi.mocked(disablePublicShare).mockReset()
    vi.mocked(rotatePublicShare).mockReset()
    Object.assign(navigator, { clipboard: { writeText: vi.fn() } })
    document.execCommand = vi.fn(() => true)
  })
  afterEach(() => vi.useRealTimers())

  it("enables sharing, composes a canonical URL, copies it, disables it, and closes", async () => {
    vi.mocked(enablePublicShare).mockResolvedValue({ slug: "new", url: "", enabled: true })
    vi.mocked(disablePublicShare).mockResolvedValue(undefined)
    render(<SharePublicLinkModal workspaceId="ws" initialEnabled={false} initialSlug={null} origin="https://app.test/" onClose={close} />)
    fireEvent.click(screen.getByRole("button", { name: "Enable public sharing" }))
    expect(await screen.findByLabelText("Public URL")).toHaveTextContent("https://app.test/p/new")
    fireEvent.click(screen.getByRole("button", { name: "Copy" }))
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("https://app.test/p/new"))
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("radio", { name: "Disabled" }))
    expect(await screen.findByRole("button", { name: "Enable public sharing" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("dialog"))
    expect(close).toHaveBeenCalled()
  })

  it("rotates an existing backend URL and uses clipboard fallback", async () => {
    vi.mocked(rotatePublicShare).mockResolvedValue({ slug: "rotated", url: "https://cdn.test/p/rotated", enabled: true })
    vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error("denied"))
    render(<SharePublicLinkModal workspaceId="ws" initialEnabled initialSlug="old" onClose={close} />)
    fireEvent.click(screen.getByRole("button", { name: "Rotate public link" }))
    expect(await screen.findByText("https://cdn.test/p/rotated")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Copy" }))
    await waitFor(() => expect(document.execCommand).toHaveBeenCalledWith("copy"))
    expect(document.querySelector("textarea")).not.toBeInTheDocument()
  })

  it.each([
    ["enable", false], ["disable", true], ["rotate", true],
  ] as const)("recovers from a failed %s action", async (action, initiallyEnabled) => {
    const failure = new Error("offline")
    if (action === "enable") vi.mocked(enablePublicShare).mockRejectedValue(failure)
    if (action === "disable") vi.mocked(disablePublicShare).mockRejectedValue(failure)
    if (action === "rotate") vi.mocked(rotatePublicShare).mockRejectedValue(failure)
    render(<SharePublicLinkModal workspaceId="ws" initialEnabled={initiallyEnabled} initialSlug={initiallyEnabled ? "old" : null} onClose={close} />)
    fireEvent.click(screen.getByRole(action === "disable" ? "radio" : "button", {
      name: action === "enable" ? "Enable public sharing" : action === "disable" ? "Disabled" : "Rotate public link",
    }))
    expect(await screen.findByText("Sharing could not be updated")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
    if (initiallyEnabled) expect(screen.getByLabelText("Public URL")).toHaveTextContent("/p/old")
    else expect(screen.getByRole("button", { name: "Enable public sharing" })).toBeInTheDocument()
  })
})

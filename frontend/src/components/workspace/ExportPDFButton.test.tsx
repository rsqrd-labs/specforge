import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { exportWorkspacePdf, getApiErrorMessage } from "../../services/api"
import { ExportPDFButton } from "./ExportPDFButton"

vi.mock("../../services/api", () => ({
  exportWorkspacePdf: vi.fn(),
  getApiErrorMessage: vi.fn((_error, fallback) => fallback),
}))

describe("ExportPDFButton", () => {
  beforeEach(() => {
    vi.mocked(exportWorkspacePdf).mockReset()
    vi.mocked(getApiErrorMessage).mockClear()
    URL.createObjectURL = vi.fn(() => "blob:pdf")
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => vi.useRealTimers())

  it("downloads a safely named PDF and revokes its URL", async () => {
    vi.useFakeTimers()
    vi.mocked(exportWorkspacePdf).mockResolvedValue(new Blob(["pdf"]))
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    render(<ExportPDFButton workspaceId="ws-1" workspaceName="  My / Workspace!  " disabled={false} allFinalised />)
    fireEvent.click(screen.getByRole("button", { name: "Export PDF" }))
    await vi.waitFor(() => expect(exportWorkspacePdf).toHaveBeenCalledWith("ws-1"))
    expect(click).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1_500)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:pdf")
    click.mockRestore()
  })

  it("does not execute while disabled", () => {
    render(<ExportPDFButton workspaceId="ws" workspaceName="x" disabled disabledReason="Finalise first" allFinalised={false} />)
    expect(screen.getByRole("button", { name: "Export PDF" })).toBeDisabled()
    expect(screen.getByRole("button").parentElement).toHaveAttribute("data-tooltip", "Finalise first")
  })

  it("keeps a recoverable error until dismissal and supports retry", async () => {
    vi.mocked(exportWorkspacePdf)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(new Blob(["pdf"]))
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    render(<ExportPDFButton workspaceId="ws" workspaceName="---" disabled={false} allFinalised={false} />)
    fireEvent.click(screen.getByRole("button", { name: "Export PDF" }))
    expect(await screen.findByText("PDF export failed")).toBeInTheDocument()
    expect(getApiErrorMessage).toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    await waitFor(() => expect(exportWorkspacePdf).toHaveBeenCalledTimes(2))
  })
})

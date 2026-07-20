import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { getTemplates } from "../../services/api"
import type { Template } from "../../types/template"
import { TemplatesStrip } from "./TemplatesStrip"

vi.mock("../../services/api", () => ({ getTemplates: vi.fn() }))

const template: Template = {
  id: "tpl-1", slug: "auth", name: "Auth starter", description: "Secure login",
  category: "auth", problem_statement: "Build auth", sort_order: 1, active: true,
  created_at: "2026-01-01T00:00:00Z",
}

describe("TemplatesStrip", () => {
  beforeEach(() => vi.mocked(getTemplates).mockReset())

  it("stays quiet for an empty catalog and after unmount", async () => {
    vi.mocked(getTemplates).mockResolvedValueOnce([])
    const { container } = render(<TemplatesStrip onPick={vi.fn()} />)
    await waitFor(() => expect(getTemplates).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()

    let resolve!: (templates: Template[]) => void
    vi.mocked(getTemplates).mockReturnValueOnce(new Promise((done) => { resolve = done }))
    const pending = render(<TemplatesStrip onPick={vi.fn()} />)
    pending.unmount()
    resolve([template])
  })

  it("renders a scrollable catalog and selects a template", async () => {
    vi.mocked(getTemplates).mockResolvedValue([template])
    const onPick = vi.fn()
    const { container } = render(<TemplatesStrip prominent onPick={onPick} />)
    const rail = await screen.findByRole("list")
    Object.defineProperties(rail, {
      clientWidth: { configurable: true, value: 300 },
      scrollWidth: { configurable: true, value: 900 },
      scrollLeft: { configurable: true, writable: true, value: 0 },
    })
    rail.scrollBy = vi.fn()
    fireEvent(window, new Event("resize"))
    const next = await screen.findByRole("button", { name: "Scroll templates right" })
    fireEvent.click(next)
    expect(rail.scrollBy).toHaveBeenCalledWith({ left: 320, behavior: "smooth" })

    rail.scrollLeft = 400
    fireEvent.scroll(rail)
    const previous = screen.getByRole("button", { name: "Scroll templates left" })
    fireEvent.click(previous)
    expect(rail.scrollBy).toHaveBeenCalledWith({ left: -320, behavior: "smooth" })

    fireEvent.click(screen.getByRole("button", { name: "Use the Auth starter template" }))
    expect(onPick).toHaveBeenCalledWith(template)
    expect(container.querySelector(".templates-strip")).toHaveClass("prominent")
  })
})

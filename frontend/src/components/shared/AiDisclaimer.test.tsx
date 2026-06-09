import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { AI_DISCLAIMER_COPY, AiDisclaimer } from "./AiDisclaimer"

describe("AiDisclaimer", () => {
  it("renders the exact default AI disclosure copy as a visible note", () => {
    render(<AiDisclaimer />)

    const note = screen.getByRole("note")
    expect(note).toHaveTextContent(AI_DISCLAIMER_COPY)
  })

  it("supports footer, sidebar, and inline variants", () => {
    const { rerender } = render(<AiDisclaimer variant="footer" />)
    expect(screen.getByRole("note")).toHaveClass("ai-disclaimer--footer")

    rerender(<AiDisclaimer variant="sidebar" />)
    expect(screen.getByRole("note")).toHaveClass("ai-disclaimer--sidebar")

    rerender(<AiDisclaimer variant="inline" />)
    expect(screen.getByRole("note")).toHaveClass("ai-disclaimer--inline")
  })
})

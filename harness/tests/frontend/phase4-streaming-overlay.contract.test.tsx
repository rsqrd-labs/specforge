/**
 * Harness contract for T-054: StreamingOverlay component.
 * RED before T-054 is implemented (StreamingOverlay.tsx does not exist).
 * GREEN after the component is created and mounted in Workspace.tsx.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

// This import will fail (RED) until T-054 creates the file.
import { StreamingOverlay } from "../../../frontend/src/components/workspace/StreamingOverlay"

describe("T-054: StreamingOverlay component", () => {
  it("renders a visible overlay element when isVisible is true", () => {
    const { container } = render(<StreamingOverlay isVisible={true} />)
    expect(container.firstChild).not.toBeNull()
  })

  it("renders nothing when isVisible is false", () => {
    const { container } = render(<StreamingOverlay isVisible={false} />)
    expect(container.firstChild).toBeNull()
  })

  it("displays a 'Generating' label so users know the AI is working", () => {
    render(<StreamingOverlay isVisible={true} />)
    expect(screen.getByText(/generating/i)).toBeInTheDocument()
  })

  it("uses pointer-events-none so the overlay does not block scrolling", () => {
    const { container } = render(<StreamingOverlay isVisible={true} />)
    const overlayEl = container.firstChild as HTMLElement
    // Accept either inline style or Tailwind class
    const hasPointerEventsNone =
      overlayEl.style.pointerEvents === "none" ||
      overlayEl.className.includes("pointer-events-none")
    expect(hasPointerEventsNone).toBe(true)
  })
})

/**
 * Harness contract for T-054: StreamingOverlay component.
 * RED before T-054 is implemented (StreamingOverlay.tsx does not exist).
 * GREEN after the component is created and mounted in Workspace.tsx.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

// This import will fail (RED) until T-054 creates the file.
import { StreamingOverlay } from "../../../frontend/src/components/workspace/StreamingOverlay"

describe("T-054: StreamingOverlay component", () => {
  const activity = {
    stageId: "spec-id",
    stageType: "spec" as const,
    operation: "generate" as const,
    actionLabel: "generate",
    startedAt: Date.now(),
    streamed: true,
  }

  it("renders a visible overlay element when isVisible is true", () => {
    const { container } = render(
      <StreamingOverlay isVisible activity={activity} />,
    )
    expect(container.firstChild).not.toBeNull()
  })

  it("renders nothing when isVisible is false", () => {
    const { container } = render(<StreamingOverlay isVisible={false} />)
    expect(container.firstChild).toBeNull()
  })

  it("announces that generation is active", () => {
    render(<StreamingOverlay isVisible activity={activity} />)
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true")
    expect(screen.getByText(/structuring requirements/i)).toBeInTheDocument()
  })

  it("keeps server-side cancellation available while loading", () => {
    render(
      <StreamingOverlay isVisible activity={activity} onCancel={vi.fn()} />,
    )
    expect(
      screen.getByRole("button", { name: /cancel generation/i }),
    ).toBeEnabled()
  })
})

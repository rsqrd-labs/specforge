import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { StageEditor } from "./StageEditor"

describe("StageEditor", () => {
  it("reacts to readOnly changes after mount and explains the lock", async () => {
    const onContentChange = vi.fn()
    const { container, rerender } = render(
      <StageEditor
        stageId="stage-1"
        initialContent="Initial content"
        onContentChange={onContentChange}
      />,
    )

    const editor = await waitFor(() => {
      const node = container.querySelector(".cm-content")
      expect(node).not.toBeNull()
      return node as HTMLElement
    })
    expect(editor).toHaveAttribute("contenteditable", "true")

    rerender(
      <StageEditor
        stageId="stage-1"
        initialContent="Initial content"
        readOnly
        readOnlyReason="Editing paused. Editing resumes when generation finishes."
        onContentChange={onContentChange}
      />,
    )

    const lockedEditor = await waitFor(() => {
      const node = container.querySelector(".cm-content")
      expect(node).not.toBeNull()
      expect(node).toHaveAttribute("contenteditable", "false")
      return node as HTMLElement
    })
    expect(screen.getByText(/editing resumes when generation finishes/i)).toBeInTheDocument()

    fireEvent.input(lockedEditor, { target: { textContent: "Changed while locked" } })
    expect(onContentChange).not.toHaveBeenCalled()
  })
})

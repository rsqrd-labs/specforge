import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useRef } from "react"
import { describe, expect, it, vi } from "vitest"
import { useFocusTrap } from "../hooks/useFocusTrap"

function Dialog({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useFocusTrap(ref, onClose)
  return (
    <div ref={ref} data-testid="dialog">
      <button>First</button>
      <button>Second</button>
      <button>Last</button>
    </div>
  )
}

describe("useFocusTrap", () => {
  it("focuses the first focusable element on mount", () => {
    render(<Dialog onClose={vi.fn()} />)
    expect(screen.getByText("First")).toHaveFocus()
  })

  it("Tab from last element wraps focus to first", async () => {
    const user = userEvent.setup()
    render(<Dialog onClose={vi.fn()} />)
    screen.getByText("Last").focus()
    await user.tab()
    expect(screen.getByText("First")).toHaveFocus()
  })

  it("Shift+Tab from first element wraps focus to last", async () => {
    const user = userEvent.setup()
    render(<Dialog onClose={vi.fn()} />)
    screen.getByText("First").focus()
    await user.tab({ shift: true })
    expect(screen.getByText("Last")).toHaveFocus()
  })

  it("Escape key calls onClose", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Dialog onClose={onClose} />)
    await user.keyboard("{Escape}")
    expect(onClose).toHaveBeenCalledOnce()
  })
})

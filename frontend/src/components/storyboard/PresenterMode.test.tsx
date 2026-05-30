import { act, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PresenterMode } from "./PresenterMode"
import {
  DEFAULT_TEST_PERMISSIONS,
  makeStoryboardPayload,
} from "./testPayload"

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe("PresenterMode", () => {
  it("shows current slide, next slide, timer, speaker cues, demo cue, and backup points", () => {
    vi.useFakeTimers()
    render(<PresenterMode payload={makeStoryboardPayload()} isOwner />)

    expect(screen.getByLabelText(/current slide/i)).toHaveTextContent(
      /opening thesis headline/i,
    )
    expect(screen.getByLabelText(/next slide/i)).toHaveTextContent(
      /product vision headline/i,
    )
    expect(screen.getByLabelText(/speaker notes/i)).toHaveTextContent(
      /opening thesis talk track/i,
    )
    expect(screen.getByText(/opening thesis transition/i)).toBeInTheDocument()
    expect(screen.getByText(/opening thesis pause cue/i)).toBeInTheDocument()
    expect(screen.getByText(/opening thesis demo cue/i)).toBeInTheDocument()
    expect(screen.getByText(/opening thesis backup point/i)).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(screen.getByText("0:02")).toBeInTheDocument()
  })

  it("keeps public speaker notes private unless notes permission is enabled", () => {
    const payload = makeStoryboardPayload()
    const { rerender } = render(
      <PresenterMode
        payload={payload}
        publicView
        permissions={DEFAULT_TEST_PERMISSIONS}
      />,
    )

    expect(screen.getByText(/speaker notes are private/i)).toBeInTheDocument()
    expect(screen.queryByText(/opening thesis talk track/i)).toBeNull()

    rerender(
      <PresenterMode
        payload={payload}
        publicView
        permissions={{ ...DEFAULT_TEST_PERMISSIONS, allow_notes_download: true }}
      />,
    )

    expect(screen.getByText(/opening thesis talk track/i)).toBeInTheDocument()
  })
})

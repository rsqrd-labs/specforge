import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { DiffViewer } from "./DiffViewer"

describe("DiffViewer", () => {
  it("disables accept and reject with a clear lock reason", async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn()
    const onReject = vi.fn()

    render(
      <DiffViewer
        diff={"@@\n-old\n+new"}
        original="old"
        proposed="new"
        onAccept={onAccept}
        onReject={onReject}
        disabled
        disabledReason="Editing resumes when generation finishes."
      />,
    )

    const reject = screen.getByRole("button", { name: "Reject" })
    const accept = screen.getByRole("button", { name: /accept changes/i })
    expect(reject).toBeDisabled()
    expect(accept).toBeDisabled()
    expect(accept).toHaveAccessibleDescription(
      /editing resumes when generation finishes/i,
    )

    await user.click(reject)
    await user.click(accept)
    expect(onReject).not.toHaveBeenCalled()
    expect(onAccept).not.toHaveBeenCalled()
  })
})

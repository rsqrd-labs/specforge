import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import Landing from "../pages/Landing"

describe("Landing", () => {
  it("navigates to the backend Google auth endpoint on button click", async () => {
    const assignLocation = vi.fn()

    render(<Landing assignLocation={assignLocation} />)

    await userEvent.click(screen.getByRole("button", { name: /sign in with google/i }))

    expect(assignLocation).toHaveBeenCalledWith(
      `${import.meta.env.VITE_API_URL}/auth/google`,
    )
  })
})

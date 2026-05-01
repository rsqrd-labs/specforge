import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import Landing from "../pages/Landing"
import { api } from "../services/api"

vi.mock("../services/api", () => ({
  api: {
    post: vi.fn(),
  },
}))

describe("Landing", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("redirects to the backend redirect_url after starting Google auth", async () => {
    const assignLocation = vi.fn()
    vi.mocked(api.post).mockResolvedValue({
      data: {
        redirect_url: "https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
      },
    })

    render(<Landing assignLocation={assignLocation} />)

    await userEvent.click(screen.getByRole("button", { name: /sign in with google/i }))

    await waitFor(() => {
      expect(assignLocation).toHaveBeenCalledWith(
        "https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
      )
    })
  })
})

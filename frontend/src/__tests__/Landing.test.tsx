import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router"

import Landing from "../pages/Landing"

function renderLanding(props?: Parameters<typeof Landing>[0]) {
  return render(
    <MemoryRouter>
      <Landing {...props} />
    </MemoryRouter>,
  )
}

describe("Landing", () => {
  it("renders the squirrel brand lockup instead of the old SF mark", () => {
    renderLanding()

    expect(screen.getByRole("img", { name: "Thought2Build" })).toBeInTheDocument()
    expect(screen.queryByText("SF")).toBeNull()
  })

  it("navigates to the backend Google auth endpoint on button click", async () => {
    const assignLocation = vi.fn()

    renderLanding({ assignLocation })

    await userEvent.click(screen.getByRole("button", { name: /sign in with google/i }))

    expect(assignLocation).toHaveBeenCalledWith(
      `${import.meta.env.VITE_API_URL}/auth/google`,
    )
  })

  it("shows a sign-in consent line naming Terms and Privacy", () => {
    renderLanding()

    // Pins the specific microcopy (not just that some link to /legal/terms
    // exists somewhere on the page, e.g. only in the footer) — this is the
    // line a Google OAuth consent-screen review looks for.
    expect(
      screen.getByText(/by continuing you agree to our/i),
    ).toBeInTheDocument()
    expect(
      screen.getAllByRole("link", { name: "Terms of Service" }),
    ).toHaveLength(2)
    expect(
      screen.getAllByRole("link", { name: "Privacy Policy" }),
    ).toHaveLength(2)

    for (const link of screen.getAllByRole("link", { name: "Terms of Service" })) {
      expect(link).toHaveAttribute("href", "/legal/terms")
    }
    for (const link of screen.getAllByRole("link", { name: "Privacy Policy" })) {
      expect(link).toHaveAttribute("href", "/legal/privacy")
    }
  })

  it("renders a footer linking to the Data Retention Policy", () => {
    renderLanding()

    expect(
      screen.getByRole("link", { name: "Data Retention Policy" }),
    ).toHaveAttribute("href", "/legal/retention")
  })
})

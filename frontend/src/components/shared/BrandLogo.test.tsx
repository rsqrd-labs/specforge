import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { BrandLockup, BrandLogo } from "./BrandLogo"

describe("BrandLogo", () => {
  it("renders the squirrel mark as an accessible image by default", () => {
    const { container } = render(<BrandLogo />)

    expect(
      screen.getByRole("img", { name: "Thought2Build squirrel logo" }),
    ).toBeInTheDocument()
    const mark = container.querySelector(".brand-logo-image")
    expect(mark).not.toBeNull()
    expect(mark?.tagName.toLowerCase()).toBe("svg")
    expect(screen.queryByText("SF")).toBeNull()
  })

  it("can render as a decorative mark for surrounding lockups", () => {
    const { container } = render(<BrandLogo decorative size="small" />)

    expect(screen.queryByRole("img")).toBeNull()
    expect(container.querySelector(".brand-logo--small")).not.toBeNull()
  })
})

describe("BrandLockup", () => {
  it("renders the squirrel mark with the Thought2Build wordmark", () => {
    const { container } = render(<BrandLockup />)

    expect(screen.getByRole("img", { name: "Thought2Build" })).toBeInTheDocument()
    expect(screen.getByText("Thought2Build")).toBeInTheDocument()
    expect(container.querySelector(".brand-logo-image")).not.toBeNull()
    expect(screen.queryByText("SF")).toBeNull()
  })

  it("supports small and compact variants", () => {
    const { rerender } = render(<BrandLockup variant="small" />)
    expect(screen.getByRole("img", { name: "Thought2Build" })).toHaveClass(
      "brand-lockup--small",
    )

    rerender(<BrandLockup variant="compact" />)
    expect(screen.getByRole("img", { name: "Thought2Build" })).toHaveClass(
      "brand-lockup--compact",
    )
  })
})

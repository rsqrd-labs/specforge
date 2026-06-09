import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { BrandLockup, BrandLogo } from "./BrandLogo"

describe("BrandLogo", () => {
  it("renders the squirrel mark as an accessible image by default", () => {
    const { container } = render(<BrandLogo />)

    expect(
      screen.getByRole("img", { name: "SpecForge squirrel logo" }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("img", { name: "SpecForge squirrel logo" }),
    ).toHaveAttribute("src", "/brand/squirrel-mark.png")
    expect(container.querySelector(".brand-logo-image")).not.toBeNull()
    expect(screen.queryByText("SF")).toBeNull()
  })

  it("can render as a decorative mark for surrounding lockups", () => {
    const { container } = render(<BrandLogo decorative size="small" />)

    expect(screen.queryByRole("img")).toBeNull()
    expect(container.querySelector(".brand-logo--small")).not.toBeNull()
  })
})

describe("BrandLockup", () => {
  it("renders the squirrel mark with the SpecForge wordmark", () => {
    const { container } = render(<BrandLockup />)

    expect(screen.getByRole("img", { name: "SpecForge" })).toBeInTheDocument()
    expect(screen.getByText("SpecForge")).toBeInTheDocument()
    expect(container.querySelector(".brand-logo-image")).not.toBeNull()
    expect(screen.queryByText("SF")).toBeNull()
  })

  it("supports small and compact variants", () => {
    const { rerender } = render(<BrandLockup variant="small" />)
    expect(screen.getByRole("img", { name: "SpecForge" })).toHaveClass(
      "brand-lockup--small",
    )

    rerender(<BrandLockup variant="compact" />)
    expect(screen.getByRole("img", { name: "SpecForge" })).toHaveClass(
      "brand-lockup--compact",
    )
  })
})

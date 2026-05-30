import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { SourceLayer } from "./SourceLayer"
import {
  DEFAULT_TEST_PERMISSIONS,
  makeStoryboardPayload,
} from "./testPayload"

describe("SourceLayer", () => {
  it("shows source badges and opens bounded excerpts only after a badge click", async () => {
    const user = userEvent.setup()
    const { container } = render(
      <SourceLayer
        payload={makeStoryboardPayload()}
        currentSlideId="opening-thesis-slide"
        isOwner
      />,
    )

    expect(screen.getByRole("button", { name: /SPEC/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /PLAN/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /HARNESS/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /TASKS/i })).toBeInTheDocument()
    expect(container.querySelector(".source-layer__excerpts p")).toBeNull()

    await user.click(screen.getByRole("button", { name: /SPEC/i }))

    const excerpt = container.querySelector(".source-layer__excerpts p")
    expect(excerpt?.textContent?.length).toBeLessThanOrEqual(1203)
    expect(excerpt?.textContent?.endsWith("...")).toBe(true)
  })

  it("respects public allow_source_layer permission", async () => {
    const user = userEvent.setup()
    const payload = makeStoryboardPayload()
    const { rerender } = render(
      <SourceLayer
        payload={payload}
        currentSlideId="opening-thesis-slide"
        publicView
        permissions={DEFAULT_TEST_PERMISSIONS}
      />,
    )

    expect(screen.getByText(/require owner access/i)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /SPEC/i })).toBeNull()

    rerender(
      <SourceLayer
        payload={payload}
        currentSlideId="opening-thesis-slide"
        publicView
        permissions={{ ...DEFAULT_TEST_PERMISSIONS, allow_source_layer: true }}
      />,
    )

    await user.click(screen.getByRole("button", { name: /SPEC/i }))
    expect(screen.getByText(/SPEC:source/i)).toBeInTheDocument()
  })
})

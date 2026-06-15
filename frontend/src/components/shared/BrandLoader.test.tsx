import { act, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { BrandLoader } from "./BrandLoader"

/**
 * jsdom ships neither `matchMedia` nor a settable `document.hidden`, so each
 * test installs exactly the environment it asserts against and restores it
 * afterwards. This keeps the reduced-motion and visibility branches honest
 * rather than silently falling through to the defaults.
 */
function mockMatchMedia(matches: boolean) {
  const mql = {
    matches,
    media: "(prefers-reduced-motion: reduce)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }
  window.matchMedia = vi.fn().mockReturnValue(mql) as unknown as typeof window.matchMedia
  return mql
}

function setDocumentHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  // Reset the visibility override so it never leaks into another test.
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => false,
  })
})

describe("BrandLoader", () => {
  it("inline variant owns a polite status region and announces its label", () => {
    mockMatchMedia(false)
    render(<BrandLoader variant="inline" label="Saving changes…" />)

    const status = screen.getByRole("status")
    expect(status).toHaveAttribute("aria-live", "polite")
    expect(status).toHaveAttribute("aria-busy", "true")
    expect(status).toHaveClass("brand-loader--inline")
    expect(status).toHaveTextContent("Saving changes…")
  })

  it("falls back to a screen-reader-only 'Loading' when no label is given", () => {
    mockMatchMedia(false)
    const { container } = render(<BrandLoader variant="block" />)

    expect(screen.getByRole("status")).toHaveTextContent("Loading")
    expect(container.querySelector(".brand-loader-sr")).not.toBeNull()
  })

  it("renders the animated CSS mark (no extra network/runtime asset)", () => {
    mockMatchMedia(false)
    const { container } = render(<BrandLoader variant="block" />)

    expect(container.querySelector(".brand-loader-mark svg")).not.toBeNull()
    // The static raster mark must NOT be mounted while animating.
    expect(container.querySelector(".brand-logo-image")).toBeNull()
  })

  it("overlay variant is decorative — no nested live region", () => {
    mockMatchMedia(false)
    const { container } = render(<BrandLoader variant="overlay" label="Generating" />)

    expect(screen.queryByRole("status")).toBeNull()
    const root = container.querySelector(".brand-loader--overlay")
    expect(root).not.toBeNull()
    expect(root).toHaveAttribute("aria-hidden", "true")
  })

  it("renders the static brand mark instead of the animation under prefers-reduced-motion", () => {
    mockMatchMedia(true)
    const { container } = render(<BrandLoader variant="block" label="Loading" />)

    // Static sibling is shown; the animated mark is not mounted.
    expect(container.querySelector(".brand-logo-image")).not.toBeNull()
    expect(container.querySelector(".brand-loader-mark")).toBeNull()
    // The status region still announces without any motion.
    expect(screen.getByRole("status")).toHaveTextContent("Loading")
  })

  it("gives each instance a unique gradient id so co-located loaders never collide", () => {
    mockMatchMedia(false)
    const { container } = render(
      <>
        <BrandLoader variant="inline" />
        <BrandLoader variant="inline" />
      </>,
    )

    const gradients = Array.from(container.querySelectorAll("linearGradient"))
    expect(gradients).toHaveLength(2)
    const ids = gradients.map((node) => node.id)
    expect(new Set(ids).size).toBe(2)
    // Colons would make `url(#id)` an unreliable reference target.
    expect(ids.every((id) => !id.includes(":"))).toBe(true)
  })

  it("pauses the animation when the tab is hidden", () => {
    mockMatchMedia(false)
    setDocumentHidden(false)
    const { container } = render(<BrandLoader variant="block" />)

    expect(container.querySelector(".brand-loader-mark.is-paused")).toBeNull()

    act(() => {
      setDocumentHidden(true)
      document.dispatchEvent(new Event("visibilitychange"))
    })

    expect(container.querySelector(".brand-loader-mark.is-paused")).not.toBeNull()
  })
})

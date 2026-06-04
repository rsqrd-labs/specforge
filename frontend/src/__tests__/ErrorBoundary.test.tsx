/**
 * Tests for the reusable ErrorBoundary component.
 *
 * React logs caught errors to console.error even inside an error boundary —
 * we spy on it and suppress the output so the test run stays clean.  We
 * restore the spy in afterEach so subsequent tests are unaffected.
 *
 * MF-4 — T-208.
 */
import { render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { ErrorInfo, ReactNode } from "react"

import { ErrorBoundary } from "../components/ErrorBoundary"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** A component that always throws during render. */
function ThrowingComponent(): ReactNode {
  throw new Error("intentional test error")
}

/** A component that renders normally. */
function SafeComponent() {
  return <div>Safe content rendered</div>
}

// ---------------------------------------------------------------------------
// Setup — suppress React's expected console.error noise
// ---------------------------------------------------------------------------

let consoleSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  // React 18 calls console.error when a boundary catches; silence it so
  // test output stays readable.  We assert on the spy in relevant tests.
  consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {})
})

afterEach(() => {
  consoleSpy.mockRestore()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ErrorBoundary", () => {
  it("renders children normally when no error is thrown", () => {
    render(
      <ErrorBoundary fallback={<div>Should not appear</div>}>
        <SafeComponent />
      </ErrorBoundary>,
    )

    expect(screen.getByText("Safe content rendered")).toBeInTheDocument()
    expect(screen.queryByText("Should not appear")).not.toBeInTheDocument()
  })

  it("renders the custom fallback when a child throws during render", () => {
    render(
      <ErrorBoundary fallback={<div>Custom error fallback</div>}>
        <ThrowingComponent />
      </ErrorBoundary>,
    )

    expect(screen.getByText("Custom error fallback")).toBeInTheDocument()
  })

  it("renders the default fallback (role=alert) when no fallback prop is supplied", () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>,
    )

    // The DefaultFallback has role="alert"
    expect(screen.getByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong.")
  })

  it("calls the onError callback with the thrown Error and componentStack", () => {
    // vi.fn() without explicit generics — we narrow the call args in the assertion.
    const onError = vi.fn()

    render(
      <ErrorBoundary
        fallback={<div>Fallback</div>}
        onError={onError as (error: Error, info: ErrorInfo) => void}
      >
        <ThrowingComponent />
      </ErrorBoundary>,
    )

    expect(onError).toHaveBeenCalledOnce()
    const [error, info] = onError.mock.calls[0] as [Error, ErrorInfo]
    expect(error).toBeInstanceOf(Error)
    expect(error.message).toBe("intentional test error")
    // React supplies a non-empty componentStack string
    expect(typeof info.componentStack).toBe("string")
    expect(info.componentStack!.length).toBeGreaterThan(0)
  })

  it("does not call onError when no error is thrown", () => {
    const onError = vi.fn()

    render(
      <ErrorBoundary fallback={<div>Fallback</div>} onError={onError}>
        <SafeComponent />
      </ErrorBoundary>,
    )

    expect(onError).not.toHaveBeenCalled()
  })

  it("logs the caught error to console.error for debugging visibility", () => {
    render(
      <ErrorBoundary fallback={<div>Fallback</div>}>
        <ThrowingComponent />
      </ErrorBoundary>,
    )

    // The boundary must call console.error — errors must not be silently swallowed.
    // React's dev mode may also call console.error before componentDidCatch fires,
    // so we scan all calls for the [ErrorBoundary] prefix rather than asserting on
    // the first call only.
    expect(consoleSpy).toHaveBeenCalled()
    const allMessages = consoleSpy.mock.calls.map((args: unknown[]) =>
      String(args[0]),
    )
    expect(allMessages.some((msg: string) => msg.includes("[ErrorBoundary]"))).toBe(
      true,
    )
  })

  it("renders fallback even when onError prop is absent", () => {
    // Regression: verify that the optional-chaining on onError? does not throw
    render(
      <ErrorBoundary fallback={<div>No callback fallback</div>}>
        <ThrowingComponent />
      </ErrorBoundary>,
    )

    expect(screen.getByText("No callback fallback")).toBeInTheDocument()
  })
})

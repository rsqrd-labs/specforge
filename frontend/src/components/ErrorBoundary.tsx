import { Component, type ErrorInfo, type ReactNode } from "react"

// ---------------------------------------------------------------------------
// Props / State
// ---------------------------------------------------------------------------

export interface ErrorBoundaryProps {
  /**
   * Fallback UI rendered in place of the crashed subtree.
   * Defaults to a generic "Something went wrong" inline message so callers
   * that don't supply a custom fallback still see something meaningful instead
   * of a blank region.
   */
  fallback?: ReactNode
  /**
   * Optional hook for error reporting (e.g. Sentry).
   * Called once per caught error with the thrown Error and React's component
   * stack string (as ErrorInfo.componentStack).
   */
  onError?: (error: Error, info: ErrorInfo) => void
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
}

// ---------------------------------------------------------------------------
// Default fallback — used when the caller omits the `fallback` prop
// ---------------------------------------------------------------------------

function DefaultFallback() {
  return (
    <div className="error-boundary-default" role="alert" aria-live="polite">
      <span>Something went wrong.</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ErrorBoundary
// ---------------------------------------------------------------------------

/**
 * Reusable React error boundary.
 *
 * Catches render-time exceptions thrown by any descendant and shows a
 * fallback UI in their place so an isolated component failure cannot
 * propagate to the nearest parent boundary and crash the whole page.
 *
 * The component always logs to console.error for visibility in development
 * DevTools / CI output. If an `onError` prop is supplied (e.g. Sentry's
 * `captureException`) it is called immediately after the console log.
 *
 * Example:
 * ```tsx
 * <ErrorBoundary
 *   fallback={<TemplatesErrorFallback />}
 *   onError={(err, info) => Sentry.captureException(err, { extra: info })}
 * >
 *   <TemplatesStrip ... />
 * </ErrorBoundary>
 * ```
 *
 * MF-4 — T-208.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    // Update state so the next render shows the fallback UI.
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Always write to console.error — errors must not be silently swallowed.
    console.error("[ErrorBoundary] caught render error:", error, info.componentStack)
    // Delegate to the optional reporting hook (e.g. Sentry) if provided.
    this.props.onError?.(error, info)
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return this.props.fallback ?? <DefaultFallback />
    }
    return this.props.children
  }
}

export default ErrorBoundary

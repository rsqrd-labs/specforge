import { useCallback, useEffect, useRef, useState } from "react"
import {
  disablePublicShare,
  enablePublicShare,
  getApiErrorMessage,
  rotatePublicShare,
} from "../../services/api"
import { useFocusTrap } from "../../hooks/useFocusTrap"
import type { ShareLinkResponse } from "../../types/publicShare"

interface SharePublicLinkModalProps {
  workspaceId: string
  /**
   * Initial enabled state from the workspace response (T-161 fields).
   * The modal manages its own enabled state thereafter.
   */
  initialEnabled: boolean
  /** Initial slug if already issued; null means no slug allocated yet. */
  initialSlug: string | null
  /** Origin used to compose the canonical URL when the backend response lacks one. */
  origin?: string
  onClose: () => void
}

type ModalState =
  | { kind: "loading" }
  | { kind: "disabled" }
  | { kind: "enabled"; slug: string; url: string }
  | { kind: "error"; message: string }

function composeUrl(slug: string, origin?: string): string {
  const base = (origin ?? window.location.origin).replace(/\/$/, "")
  return `${base}/p/${slug}`
}

/**
 * T-USE-10 — workspace share modal (Surface A).
 *
 * The URL is the hero of the modal — large monospaced pill with the saffron
 * Copy button glued to its right edge. Toggle is a quiet two-radio row, not
 * a switch. Rotate sits behind a `<details>` disclosure so it can never be
 * triggered by a single accidental click — rotating invalidates the live URL.
 *
 * Empty 404 is invisible at the public-view layer; here, failures bubble up
 * to a single inline error chip with retry.
 */
export function SharePublicLinkModal({
  workspaceId,
  initialEnabled,
  initialSlug,
  origin,
  onClose,
}: SharePublicLinkModalProps) {
  const [state, setState] = useState<ModalState>(() => {
    if (initialEnabled && initialSlug) {
      return { kind: "enabled", slug: initialSlug, url: composeUrl(initialSlug, origin) }
    }
    return { kind: "disabled" }
  })
  const [copiedAt, setCopiedAt] = useState<number | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const modalRef = useRef<HTMLDivElement | null>(null)
  // Trap focus within the modal so Tab/Shift+Tab cycle through interactive
  // elements and keyboard users cannot reach background content.
  // WCAG 2.1 SC 2.1.2 — L-6 / T-189b.
  useFocusTrap(modalRef, onClose)

  useEffect(() => {
    closeRef.current?.focus()
  }, [])

  // Reset the Copied! pulse after the 1.2s window so consecutive copies
  // re-show the affirmation. setTimeout cleared on unmount.
  useEffect(() => {
    if (copiedAt === null) return
    const handle = window.setTimeout(() => setCopiedAt(null), 1_200)
    return () => window.clearTimeout(handle)
  }, [copiedAt])

  const applyLink = useCallback(
    (link: ShareLinkResponse) => {
      const url = link.url || composeUrl(link.slug, origin)
      setState({ kind: "enabled", slug: link.slug, url })
    },
    [origin],
  )

  const handleEnable = useCallback(async () => {
    setState({ kind: "loading" })
    try {
      const link = await enablePublicShare(workspaceId)
      applyLink(link)
    } catch (exc) {
      setState({
        kind: "error",
        message: getApiErrorMessage(
          exc,
          "Couldn't enable sharing. Make sure every stage is finalised.",
        ),
      })
    }
  }, [workspaceId, applyLink])

  const handleDisable = useCallback(async () => {
    setState({ kind: "loading" })
    try {
      await disablePublicShare(workspaceId)
      setState({ kind: "disabled" })
    } catch (exc) {
      setState({
        kind: "error",
        message: getApiErrorMessage(exc, "Couldn't disable sharing. Try again?"),
      })
    }
  }, [workspaceId])

  const handleRotate = useCallback(async () => {
    setState({ kind: "loading" })
    try {
      const link = await rotatePublicShare(workspaceId)
      applyLink(link)
    } catch (exc) {
      setState({
        kind: "error",
        message: getApiErrorMessage(exc, "Couldn't rotate the link. Try again?"),
      })
    }
  }, [workspaceId, applyLink])

  const handleCopy = useCallback(async () => {
    if (state.kind !== "enabled") return
    try {
      await navigator.clipboard.writeText(state.url)
      setCopiedAt(Date.now())
    } catch {
      // Some browsers reject clipboard writes in non-secure contexts; fall
      // back to a select+execCommand path silently.
      const fallback = document.createElement("textarea")
      fallback.value = state.url
      document.body.appendChild(fallback)
      fallback.select()
      try {
        document.execCommand("copy")
        setCopiedAt(Date.now())
      } finally {
        document.body.removeChild(fallback)
      }
    }
  }, [state])

  return (
    <div
      className="create-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-modal-title"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div ref={modalRef} className="create-modal share-modal">
        <header className="create-modal-header">
          <h2 id="share-modal-title" className="create-modal-title">Share publicly</h2>
          <button
            ref={closeRef}
            type="button"
            className="create-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </header>

        <div className="create-modal-body share-modal-body">
          {state.kind === "loading" && (
            <p className="share-modal-loading">Working…</p>
          )}

          {state.kind === "disabled" && (
            <div className="share-modal-disabled">
              <p className="share-modal-lede">
                Publish a read-only view of this finalised spec at a shareable URL.
              </p>
              <button
                type="button"
                className="modal-submit"
                onClick={() => void handleEnable()}
              >
                Enable public sharing
              </button>
            </div>
          )}

          {state.kind === "enabled" && (
            <>
              <div className="share-modal-url-row">
                <span
                  className="share-modal-url"
                  title={state.url}
                  aria-label="Public URL"
                >
                  {state.url}
                </span>
                <button
                  type="button"
                  className={`share-modal-copy ${copiedAt ? "copied" : ""}`}
                  onClick={() => void handleCopy()}
                >
                  {copiedAt ? "Copied ✓" : "Copy"}
                </button>
              </div>

              <div
                className="share-modal-toggle-row"
                role="radiogroup"
                aria-label="Visibility"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={true}
                  className="share-modal-radio active"
                >
                  Public
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={false}
                  className="share-modal-radio"
                  onClick={() => void handleDisable()}
                >
                  Disabled
                </button>
              </div>

              <details className="share-modal-more">
                <summary>More</summary>
                <div className="share-modal-rotate">
                  <p className="share-modal-rotate-copy">
                    Rotating invalidates the current link. Anyone holding it
                    will see a 404.
                  </p>
                  <button
                    type="button"
                    className="share-modal-rotate-btn"
                    onClick={() => void handleRotate()}
                  >
                    Rotate link
                  </button>
                </div>
              </details>
            </>
          )}

          {state.kind === "error" && (
            <div className="share-modal-error" role="alert">
              <span>{state.message}</span>
              <button
                type="button"
                className="share-modal-error-retry"
                onClick={() =>
                  initialEnabled && initialSlug
                    ? applyLink({
                        slug: initialSlug,
                        url: composeUrl(initialSlug, origin),
                        enabled: true,
                      })
                    : setState({ kind: "disabled" })
                }
              >
                Dismiss
              </button>
            </div>
          )}
        </div>

        <footer className="share-modal-footer">
          <p className="share-modal-privacy">
            Anyone with the link can view your finalised SPEC.md, PLAN.md,
            HARNESS coverage, and TASKS.md. They cannot see your credit
            balance, billing, account email, other workspaces, or any
            draft / pre-finalisation content.
          </p>
        </footer>
      </div>
    </div>
  )
}

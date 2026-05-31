import { useMemo, useState } from "react"
import {
  disableStoryboardShare,
  rotateStoryboardShare,
  shareStoryboard,
} from "../../services/api"
import type {
  StoryboardSharePermissions,
  StoryboardShareResponse,
} from "../../types/storyboard"

export const DEFAULT_SHARE_PERMISSIONS: StoryboardSharePermissions = {
  allow_pdf_download: true,
  allow_notes_download: false,
  allow_appendix_download: false,
  allow_source_layer: false,
}

// The permission rows surfaced in the dialog, each with a plain-language title and
// a one-line explanation of what the viewer actually gets. `allow_appendix_download`
// is intentionally absent — the technical-appendix download is no longer offered in
// the download menu — but its stored value is preserved through save (see saveShare).
const PERMISSION_ROWS: {
  key: keyof StoryboardSharePermissions
  title: string
  description: string
}[] = [
  {
    key: "allow_pdf_download",
    title: "Download the PDF",
    description: "Viewers can save the deck as a print-ready PDF.",
  },
  {
    key: "allow_notes_download",
    title: "Download speaker notes",
    description: "Share your presenter notes as a Markdown file.",
  },
  {
    key: "allow_source_layer",
    title: "Show source evidence",
    description: "Let viewers open the panel linking each slide to its spec and plan.",
  },
]

interface ShareState {
  enabled: boolean
  slug: string | null
  permissions: StoryboardSharePermissions
}

interface StoryboardShareModalProps {
  storyboardId: string
  initialEnabled: boolean
  initialSlug: string | null
  initialPermissions?: Partial<StoryboardSharePermissions>
  onClose: () => void
  onShareChanged?: (state: ShareState) => void
}

function mergePermissions(
  permissions?: Partial<StoryboardSharePermissions>,
): StoryboardSharePermissions {
  return { ...DEFAULT_SHARE_PERMISSIONS, ...permissions }
}

function shareUrl(slug: string | null): string {
  if (!slug) return ""
  return `${window.location.origin}/sb/${slug}`
}

function responseToState(response: StoryboardShareResponse): ShareState {
  return {
    enabled: response.enabled,
    slug: response.slug,
    permissions: mergePermissions(response.permissions),
  }
}

function permissionsEqual(
  a: StoryboardSharePermissions,
  b: StoryboardSharePermissions,
): boolean {
  return (
    a.allow_pdf_download === b.allow_pdf_download &&
    a.allow_notes_download === b.allow_notes_download &&
    a.allow_appendix_download === b.allow_appendix_download &&
    a.allow_source_layer === b.allow_source_layer
  )
}

export function StoryboardShareModal({
  storyboardId,
  initialEnabled,
  initialSlug,
  initialPermissions,
  onClose,
  onShareChanged,
}: StoryboardShareModalProps) {
  const [enabled, setEnabled] = useState(initialEnabled)
  const [slug, setSlug] = useState(initialSlug)
  const [permissions, setPermissions] = useState(() =>
    mergePermissions(initialPermissions),
  )
  // The permissions last persisted to the server; "Save changes" is only offered
  // when the working set drifts from this, so the dialog never fires a redundant
  // save and there is no per-toggle network race.
  const [savedPermissions, setSavedPermissions] = useState(() =>
    mergePermissions(initialPermissions),
  )
  const [isBusy, setIsBusy] = useState(false)
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle")
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const currentUrl = useMemo(() => shareUrl(slug), [slug])
  const isDirty = useMemo(
    () => !permissionsEqual(permissions, savedPermissions),
    [permissions, savedPermissions],
  )

  function updatePermission(key: keyof StoryboardSharePermissions, value: boolean) {
    setPermissions((current) => ({ ...current, [key]: value }))
    setCopyState("idle")
  }

  function applyShareState(next: ShareState) {
    setEnabled(next.enabled)
    setSlug(next.slug)
    setPermissions(next.permissions)
    setSavedPermissions(next.permissions)
    onShareChanged?.(next)
  }

  async function saveShare() {
    setIsBusy(true)
    setErrorMessage(null)
    try {
      // `permissions` carries every key (including the hidden allow_appendix_download)
      // so a previously granted value is never silently dropped on save.
      const response = await shareStoryboard(storyboardId, permissions)
      applyShareState(responseToState(response))
    } catch {
      setErrorMessage("Sharing settings could not be saved.")
    } finally {
      setIsBusy(false)
    }
  }

  async function disableShare() {
    setIsBusy(true)
    setErrorMessage(null)
    try {
      await disableStoryboardShare(storyboardId)
      applyShareState({ enabled: false, slug: null, permissions })
    } catch {
      setErrorMessage("Sharing could not be disabled.")
    } finally {
      setIsBusy(false)
    }
  }

  async function rotateShare() {
    setIsBusy(true)
    setErrorMessage(null)
    try {
      const response = await rotateStoryboardShare(storyboardId)
      applyShareState(responseToState(response))
    } catch {
      setErrorMessage("Share link could not be rotated.")
    } finally {
      setIsBusy(false)
    }
  }

  async function copyShareLink() {
    if (!currentUrl) return
    try {
      await navigator.clipboard?.writeText(currentUrl)
      setCopyState("copied")
    } catch {
      setCopyState("failed")
    }
  }

  const statusText = errorMessage
    ? errorMessage
    : copyState === "copied"
      ? "Link copied"
      : copyState === "failed"
        ? "Copy failed — select the link and copy it manually."
        : isBusy
          ? "Saving…"
          : isDirty && enabled
            ? "You have unsaved permission changes."
            : ""
  const statusRole = errorMessage || copyState === "failed" ? "alert" : "status"

  return (
    <div
      className="sb-share-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sb-share-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="sb-share">
        <header className="sb-share__head">
          <div>
            <p className="sb-share__eyebrow">Share</p>
            <h2 id="sb-share-title">Share this storyboard</h2>
            <p className="sb-share__sub">
              Publish a link anyone can open in their browser — no SpecForge account
              needed.
            </p>
          </div>
          <button
            type="button"
            className="sb-share__close"
            onClick={onClose}
            aria-label="Close share dialog"
          >
            ✕
          </button>
        </header>

        <div className="sb-share__master">
          <div className="sb-share__master-copy">
            <strong>Public link</strong>
            <span>
              {enabled
                ? "Anyone with the link can view this deck."
                : "Only you can open this storyboard right now."}
            </span>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="Public link"
            className={`sb-switch${enabled ? " is-on" : ""}`}
            disabled={isBusy}
            onClick={() => (enabled ? void disableShare() : void saveShare())}
          >
            <span className="sb-switch__dot" />
          </button>
        </div>

        <div className={`sb-share__link${enabled && currentUrl ? "" : " is-empty"}`}>
          {enabled && currentUrl ? (
            <>
              <div className="sb-share__link-row">
                <input
                  className="sb-share__link-url"
                  readOnly
                  value={currentUrl}
                  aria-label="Public storyboard link"
                  onFocus={(event) => event.currentTarget.select()}
                />
                <button
                  type="button"
                  className="sb-share__copy"
                  onClick={() => void copyShareLink()}
                >
                  {copyState === "copied" ? "Copied" : "Copy link"}
                </button>
              </div>
              <button
                type="button"
                className="sb-share__rotate"
                onClick={() => void rotateShare()}
                disabled={isBusy}
              >
                Generate new link
              </button>
              <span className="sb-share__rotate-hint">
                Replaces the current link — the old one stops working immediately.
              </span>
            </>
          ) : (
            <p className="sb-share__link-empty">
              Turn on the public link above to get a shareable URL.
            </p>
          )}
        </div>

        <div className="sb-share__perms">
          <p className="sb-share__perms-title">What viewers can do</p>
          {PERMISSION_ROWS.map((row) => (
            <label key={row.key} className="sb-perm">
              <span className="sb-perm__text">
                <strong>{row.title}</strong>
                <span>{row.description}</span>
              </span>
              <input
                type="checkbox"
                checked={permissions[row.key]}
                onChange={(event) =>
                  updatePermission(row.key, event.currentTarget.checked)
                }
              />
              <span className="sb-perm__track" aria-hidden="true">
                <span className="sb-perm__thumb" />
              </span>
            </label>
          ))}
        </div>

        <footer className="sb-share__foot">
          <p className={`sb-share__status sb-share__status--${statusRole}`} role={statusRole}>
            {statusText}
          </p>
          <div className="sb-share__foot-actions">
            <button type="button" className="sb-btn sb-btn--ghost" onClick={onClose}>
              Done
            </button>
            <button
              type="button"
              className="sb-btn sb-btn--primary"
              onClick={() => void saveShare()}
              disabled={isBusy || !enabled || !isDirty}
            >
              Save changes
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}

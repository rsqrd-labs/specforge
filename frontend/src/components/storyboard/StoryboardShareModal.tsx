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
  const [isBusy, setIsBusy] = useState(false)
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle")
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const currentUrl = useMemo(() => shareUrl(slug), [slug])

  function updatePermission(
    key: keyof StoryboardSharePermissions,
    value: boolean,
  ) {
    setPermissions((current) => ({ ...current, [key]: value }))
  }

  function applyShareState(next: ShareState) {
    setEnabled(next.enabled)
    setSlug(next.slug)
    setPermissions(next.permissions)
    onShareChanged?.(next)
  }

  async function saveShare() {
    setIsBusy(true)
    setErrorMessage(null)
    try {
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
      const next = { enabled: false, slug: null, permissions }
      applyShareState(next)
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

  return (
    <div className="storyboard-share-modal" role="dialog" aria-modal="true">
      <div className="storyboard-share-modal__panel">
        <header>
          <div>
            <span>Storyboard sharing</span>
            <h2>Public launch link</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close share modal">
            Close
          </button>
        </header>

        <label className="storyboard-share-modal__switch">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => {
              if (event.currentTarget.checked) {
                void saveShare()
              } else {
                void disableShare()
              }
            }}
            disabled={isBusy}
          />
          <span>{enabled ? "Public" : "Disabled"}</span>
        </label>

        <div className="storyboard-share-modal__url">
          <input readOnly value={currentUrl || "Enable sharing to create /sb link"} />
          <button type="button" onClick={() => void copyShareLink()} disabled={!currentUrl}>
            Copy
          </button>
        </div>

        <fieldset className="storyboard-share-modal__permissions">
          <legend>Public permissions</legend>
          <label>
            <input
              type="checkbox"
              checked={permissions.allow_pdf_download}
              onChange={(event) =>
                updatePermission("allow_pdf_download", event.currentTarget.checked)
              }
            />
            Allow PDF download
          </label>
          <label>
            <input
              type="checkbox"
              checked={permissions.allow_notes_download}
              onChange={(event) =>
                updatePermission("allow_notes_download", event.currentTarget.checked)
              }
            />
            Allow speaker notes download
          </label>
          <label>
            <input
              type="checkbox"
              checked={permissions.allow_appendix_download}
              onChange={(event) =>
                updatePermission("allow_appendix_download", event.currentTarget.checked)
              }
            />
            Allow technical appendix download
          </label>
          <label>
            <input
              type="checkbox"
              checked={permissions.allow_source_layer}
              onChange={(event) =>
                updatePermission("allow_source_layer", event.currentTarget.checked)
              }
            />
            Allow source layer
          </label>
        </fieldset>

        <footer>
          <button type="button" onClick={() => void saveShare()} disabled={isBusy}>
            {enabled ? "Save permissions" : "Enable public link"}
          </button>
          <button
            type="button"
            onClick={() => void rotateShare()}
            disabled={isBusy || !enabled}
          >
            Rotate link
          </button>
          <button
            type="button"
            onClick={() => void disableShare()}
            disabled={isBusy || !enabled}
          >
            Disable
          </button>
        </footer>

        {copyState === "copied" && <p role="status">Copied /sb link.</p>}
        {copyState === "failed" && <p role="alert">Copy failed.</p>}
        {errorMessage && <p role="alert">{errorMessage}</p>}
      </div>
    </div>
  )
}

import { useMemo, useState } from "react"
import {
  downloadPublicStoryboard,
  downloadStoryboard,
} from "../../services/api"
import type {
  StoryboardDownloadKind,
  StoryboardPublicDownloadKind,
  StoryboardSharePermissions,
} from "../../types/storyboard"

type DownloadMode = "owner" | "public"

interface DownloadItem {
  kind: StoryboardDownloadKind
  label: string
  description: string
}

interface StoryboardDownloadMenuProps {
  mode: DownloadMode
  title: string
  storyboardId?: string
  slug?: string
  permissions?: Partial<StoryboardSharePermissions>
  downloads?: StoryboardPublicDownloadKind[]
  onDownload?: (kind: StoryboardDownloadKind) => Promise<Blob | void> | Blob | void
}

const OWNER_DOWNLOADS: DownloadItem[] = [
  {
    kind: "html",
    label: "HTML package",
    description: "Offline browser keynote package.",
  },
  {
    kind: "pdf",
    label: "PDF",
    description: "Print-ready deck — one designed slide per page.",
  },
  {
    kind: "notes",
    label: "Speaker notes",
    description: "Presenter notes as Markdown.",
  },
  {
    kind: "demo-script",
    label: "Walkthrough script",
    description: "Step-by-step browser presentation runbook.",
  },
  {
    kind: "appendix",
    label: "Technical appendix",
    description: "Implementation details and backup material.",
  },
]

// File extension per download kind, so the browser saves a usable file (the
// previous name had no extension, e.g. "storyboard-deck-pdf"). Notes are always
// requested as Markdown from this menu; the rendered notes PDF is not offered here.
const DOWNLOAD_EXTENSION: Record<StoryboardDownloadKind, string> = {
  html: "html",
  pdf: "pdf",
  notes: "md",
  "demo-script": "md",
  appendix: "md",
}

function safeFilename(title: string, kind: StoryboardDownloadKind): string {
  const base = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
  return `storyboard-${base || "deck"}-${kind}.${DOWNLOAD_EXTENSION[kind]}`
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.rel = "noopener"
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function isPublicKind(kind: StoryboardDownloadKind): kind is StoryboardPublicDownloadKind {
  return kind !== "html"
}

function publicItems(
  permissions: Partial<StoryboardSharePermissions>,
  downloads: StoryboardPublicDownloadKind[],
): DownloadItem[] {
  return OWNER_DOWNLOADS.filter((item) => {
    if (!isPublicKind(item.kind) || !downloads.includes(item.kind)) return false
    if (item.kind === "pdf") return permissions.allow_pdf_download === true
    if (item.kind === "notes") return permissions.allow_notes_download === true
    if (item.kind === "appendix") return permissions.allow_appendix_download === true
    return (
      item.kind === "demo-script" &&
      (permissions.allow_appendix_download === true ||
        permissions.allow_source_layer === true)
    )
  })
}

export function StoryboardDownloadMenu({
  mode,
  title,
  storyboardId,
  slug,
  permissions = {},
  downloads = [],
  onDownload,
}: StoryboardDownloadMenuProps) {
  const [pendingKind, setPendingKind] = useState<StoryboardDownloadKind | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const items = useMemo(
    () => (mode === "owner" ? OWNER_DOWNLOADS : publicItems(permissions, downloads)),
    [downloads, mode, permissions],
  )
  // The PDF is the headline artifact — surface it as the primary action and demote
  // the rest to a secondary "More formats" group.
  const pdfItem = useMemo(() => items.find((item) => item.kind === "pdf"), [items])
  const otherItems = useMemo(
    () => items.filter((item) => item.kind !== "pdf"),
    [items],
  )

  async function handleDownload(kind: StoryboardDownloadKind) {
    setPendingKind(kind)
    setErrorMessage(null)
    try {
      const customBlob = await onDownload?.(kind)
      const blob =
        customBlob instanceof Blob
          ? customBlob
          : mode === "owner" && storyboardId
            ? await downloadStoryboard(
                storyboardId,
                kind,
                kind === "notes" ? "md" : undefined,
              )
            : mode === "public" && slug && isPublicKind(kind)
              ? await downloadPublicStoryboard(slug, kind)
              : null
      if (blob) {
        triggerBrowserDownload(blob, safeFilename(title, kind))
      }
    } catch {
      setErrorMessage("Download is not available right now.")
    } finally {
      setPendingKind(null)
    }
  }

  return (
    <section className="storyboard-download-menu" aria-label="Storyboard downloads">
      <header>
        <strong>Download</strong>
        <span>{mode === "owner" ? "Owner artifacts" : "Public artifacts"}</span>
      </header>

      {items.length > 0 ? (
        <>
          {pdfItem && (
            <button
              type="button"
              className="storyboard-download-menu__primary"
              onClick={() => void handleDownload("pdf")}
              disabled={pendingKind !== null}
            >
              <span className="storyboard-download-menu__primary-label">
                {pendingKind === "pdf" ? "Preparing PDF…" : "Download PDF"}
              </span>
              <small>{pdfItem.description}</small>
            </button>
          )}

          {otherItems.length > 0 && (
            <div className="storyboard-download-menu__more">
              <span className="storyboard-download-menu__more-label">More formats</span>
              <div className="storyboard-download-menu__items">
                {otherItems.map((item) => (
                  <button
                    key={item.kind}
                    type="button"
                    onClick={() => void handleDownload(item.kind)}
                    disabled={pendingKind !== null}
                  >
                    <span>{item.label}</span>
                    <small>{item.description}</small>
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <p>No public downloads are enabled for this Storyboard.</p>
      )}

      {errorMessage && <p role="alert">{errorMessage}</p>}
    </section>
  )
}

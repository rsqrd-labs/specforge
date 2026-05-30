import type { StoryboardStatus, StoryboardSummary } from "../../types/storyboard"
import { DownloadIcon, ShareIcon } from "../shared/icons"

type StoryboardToolbarItem = Pick<
  StoryboardSummary,
  "id" | "status" | "title" | "version"
>

interface StoryboardToolbarProps {
  storyboard: StoryboardToolbarItem
  isBusy?: boolean
  openLabel?: string
  onOpen: () => void
  onPresent: () => void
  onShare: () => void
  onDownload: () => void
  onRegenerate: () => void
  onDownloadNotes: () => void
}

function formatStatus(status: StoryboardStatus): string {
  return status.replace("_", " ")
}

export function StoryboardToolbar({
  storyboard,
  isBusy = false,
  openLabel = "Open Storyboard",
  onOpen,
  onPresent,
  onShare,
  onDownload,
  onRegenerate,
  onDownloadNotes,
}: StoryboardToolbarProps) {
  const isGenerating = storyboard.status === "generating"
  const isFailed = storyboard.status === "failed"
  const isStale = storyboard.status === "stale"
  const isPresentable = storyboard.status === "ready" || isStale
  const shareDisabled = storyboard.status !== "ready" || isBusy
  const actionDisabled = !isPresentable || isBusy

  return (
    <section
      className={`storyboard-toolbar storyboard-toolbar-${storyboard.status}`}
      aria-label="Storyboard actions"
    >
      <div className="storyboard-toolbar-copy">
        <span
          className={`storyboard-status-badge ${storyboard.status}`}
          aria-label={`Storyboard status ${formatStatus(storyboard.status)}`}
        >
          {isStale ? "Stale" : formatStatus(storyboard.status)}
        </span>
        <div>
          <strong>{storyboard.title}</strong>
          <p>
            Version {storyboard.version}
            {isStale
              ? " needs regeneration after source changes."
              : isFailed
                ? " failed; refunded credits can be used to try again."
                : isGenerating
                  ? " is generating."
                  : " is ready."}
          </p>
        </div>
      </div>

      <div className="storyboard-toolbar-actions">
        <button
          type="button"
          className="storyboard-open-button"
          onClick={onOpen}
          disabled={!isPresentable || isBusy}
        >
          {openLabel}
        </button>
        <button
          type="button"
          className="storyboard-icon-button"
          onClick={onPresent}
          disabled={actionDisabled}
          title="Present"
          aria-label="Present Storyboard"
        >
          <span>Present</span>
        </button>
        <button
          type="button"
          className="storyboard-icon-button"
          onClick={onShare}
          disabled={shareDisabled}
          title={
            storyboard.status === "ready"
              ? "Share"
              : "Sharing is available after the Storyboard is ready"
          }
          aria-label="Share Storyboard"
        >
          <ShareIcon />
          <span>Share</span>
        </button>
        <button
          type="button"
          className="storyboard-icon-button"
          onClick={onDownload}
          disabled={actionDisabled}
          title="Download"
          aria-label="Download Storyboard PDF"
        >
          <DownloadIcon />
          <span>Download</span>
        </button>
        <button
          type="button"
          className="storyboard-icon-button"
          onClick={onRegenerate}
          disabled={isGenerating || isBusy}
          title="Regenerate"
          aria-label="Regenerate Storyboard"
        >
          <span>Regenerate</span>
        </button>
        <button
          type="button"
          className="storyboard-icon-button"
          onClick={onDownloadNotes}
          disabled={actionDisabled}
          title="Download Notes"
          aria-label="Download Notes"
        >
          <DownloadIcon />
          <span>Notes</span>
        </button>
      </div>
    </section>
  )
}

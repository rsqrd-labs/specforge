import { Link } from "react-router-dom"

import { DriftIcon, GitHubIcon } from "../shared/icons"

/**
 * Two calm, informational GitHub-sync banners that share one restrained shell:
 *
 *  - "drift": when the workspace's Tasks changed since the last push
 *    (`out_of_sync`). Slate, not alarm-red — it informs and offers a quiet
 *    saffron "Re-sync changed tasks" action. It does not shout.
 *  - "disconnected": when the install is suspended/removed. The panel folds to a
 *    single slate line — "Sync paused — reconnect GitHub" — linking to Settings.
 *    No broken-looking empty panel, no raw error.
 */
interface SyncStatusBannerProps {
  variant: "drift" | "disconnected"
  resyncing?: boolean
  onResync?: () => void
}

export function SyncStatusBanner({
  variant,
  resyncing = false,
  onResync,
}: SyncStatusBannerProps) {
  if (variant === "disconnected") {
    return (
      <div className="ws-sync-banner disconnected" role="status">
        <span className="ws-sync-banner-icon" aria-hidden="true">
          <GitHubIcon />
        </span>
        <span className="ws-sync-banner-text">Sync paused</span>
        <Link to="/settings" className="ws-sync-banner-action">
          Reconnect GitHub →
        </Link>
      </div>
    )
  }

  // variant === "drift"  (out_of_sync)
  return (
    <div className="ws-sync-banner drift" role="status">
      <span className="ws-sync-banner-icon" aria-hidden="true">
        <DriftIcon />
      </span>
      <span className="ws-sync-banner-text">
        Tasks changed since the last push
      </span>
      <button
        type="button"
        className="ws-sync-banner-action"
        onClick={onResync}
        disabled={resyncing}
      >
        {resyncing ? "Re-syncing…" : "Re-sync changed tasks"}
      </button>
    </div>
  )
}

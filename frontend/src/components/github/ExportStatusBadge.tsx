import type { PushStatus } from "../../types/github"

/**
 * The four lifecycle tones the GitHub export screens speak, collapsed from the
 * backend `PushStatus` (`pending | completed | failed | stale`) plus the drift
 * flag into a single display vocabulary shared by the hub and the detail screen
 * so a repo reads identically in a list row and on its own page.
 *
 *   syncing — a push is mid-flight on the worker (pending)
 *   synced  — completed and in step with the current Tasks
 *   drift   — the spec moved on; issues on GitHub are stale (stale / out_of_sync)
 *   failed  — the export did not land
 */
export type ExportTone = "syncing" | "synced" | "drift" | "failed"

export function exportTone(status: PushStatus, outOfSync: boolean): ExportTone {
  if (status === "failed") return "failed"
  if (status === "pending") return "syncing"
  if (status === "stale" || outOfSync) return "drift"
  return "synced"
}

const LABELS: Record<ExportTone, string> = {
  syncing: "Syncing",
  synced: "Synced",
  drift: "Needs sync",
  failed: "Failed",
}

export function exportStatusLabel(
  status: PushStatus,
  outOfSync: boolean,
): string {
  return LABELS[exportTone(status, outOfSync)]
}

export function ExportStatusBadge({
  status,
  outOfSync = false,
  size = "md",
}: {
  status: PushStatus
  outOfSync?: boolean
  size?: "sm" | "md"
}) {
  const tone = exportTone(status, outOfSync)
  return (
    <span className={`ghx-badge ghx-badge-${tone} ghx-badge-${size}`}>
      <span className="ghx-badge-dot" aria-hidden="true" />
      {LABELS[tone]}
    </span>
  )
}

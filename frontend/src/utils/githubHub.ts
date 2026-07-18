import type { ExportSummary } from "../types/github"

export type GitHubHubFilter = "all" | "attention" | "syncing"
export type GitHubHubSort = "recent" | "name" | "progress"

export interface GitHubHubSummary {
  repositories: number
  shipped: number
  total: number
  attention: number
}

export function exportNeedsAttention(item: ExportSummary): boolean {
  return (
    item.status === "failed" ||
    item.sync_paused ||
    item.out_of_sync ||
    item.task_sync_status === "changes_pending"
  )
}

function activityTimestamp(item: ExportSummary): number {
  if (item.status === "pending") return Number.MAX_SAFE_INTEGER
  const timestamps = [item.last_inbound_sync_at, item.pushed_at].map((value) => {
    if (!value) return 0
    const timestamp = Date.parse(value)
    return Number.isNaN(timestamp) ? 0 : timestamp
  })
  return Math.max(...timestamps)
}

function completionRatio(item: ExportSummary): number {
  if (item.total <= 0) return 0
  return Math.min(1, Math.max(0, item.shipped / item.total))
}

function compareNames(a: ExportSummary, b: ExportSummary): number {
  return a.workspace_name.localeCompare(b.workspace_name, undefined, {
    sensitivity: "base",
  })
}

export function summarizeGitHubExports(
  rows: readonly ExportSummary[],
): GitHubHubSummary {
  return rows.reduce<GitHubHubSummary>(
    (summary, row) => ({
      repositories: summary.repositories + 1,
      shipped: summary.shipped + row.shipped,
      total: summary.total + row.total,
      attention: summary.attention + (exportNeedsAttention(row) ? 1 : 0),
    }),
    { repositories: 0, shipped: 0, total: 0, attention: 0 },
  )
}

export function selectGitHubExports(
  rows: readonly ExportSummary[],
  query: string,
  filter: GitHubHubFilter,
  sort: GitHubHubSort,
): ExportSummary[] {
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const selected = rows.filter((row) => {
    const matchesQuery =
      normalizedQuery.length === 0 ||
      row.workspace_name.toLocaleLowerCase().includes(normalizedQuery) ||
      (row.repo_full_name?.toLocaleLowerCase().includes(normalizedQuery) ?? false)

    if (!matchesQuery) return false
    if (filter === "attention") return exportNeedsAttention(row)
    if (filter === "syncing") return row.status === "pending"
    return true
  })

  return selected.sort((a, b) => {
    if (sort === "name") {
      return compareNames(a, b) || activityTimestamp(b) - activityTimestamp(a)
    }
    if (sort === "progress") {
      return (
        completionRatio(b) - completionRatio(a) ||
        activityTimestamp(b) - activityTimestamp(a) ||
        compareNames(a, b)
      )
    }
    return activityTimestamp(b) - activityTimestamp(a) || compareNames(a, b)
  })
}

/** Only render repository links that cannot execute an active URL scheme. */
export function safeGitHubUrl(value: string | null): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === "https:" &&
      url.hostname === "github.com" &&
      url.username === "" &&
      url.password === ""
      ? url.toString()
      : null
  } catch {
    return null
  }
}

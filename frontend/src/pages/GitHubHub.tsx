import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"

import { ExportStatusBadge, exportTone } from "../components/github/ExportStatusBadge"
import { BrandLogo } from "../components/shared/BrandLogo"
import { GitHubIcon } from "../components/shared/icons"
import { getApiErrorMessage, listGitHubExports } from "../services/api"
import type { ExportSummary } from "../types/github"
import {
  safeGitHubUrl,
  selectGitHubExports,
  summarizeGitHubExports,
  type GitHubHubFilter,
  type GitHubHubSort,
} from "../utils/githubHub"

const PENDING_REFRESH_INTERVAL_MS = 10_000

function SearchIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="8.5" cy="8.5" r="5.25" stroke="currentColor" strokeWidth="1.75" />
      <path d="m12.4 12.4 4 4" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  )
}

function RefreshIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M16 6.25V2.9m0 3.35h-3.35M4.1 8a6.1 6.1 0 0 1 10.35-3.2L16 6.25M4 13.75v3.35m0-3.35h3.35M15.9 12a6.1 6.1 0 0 1-10.35 3.2L4 13.75" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M11.25 3.75h5v5M9 11l7.1-7.1M16 11.25v3.5A1.25 1.25 0 0 1 14.75 16h-9.5A1.25 1.25 0 0 1 4 14.75v-9.5A1.25 1.25 0 0 1 5.25 4h3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function formatWhen(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const mins = Math.round((Date.now() - then) / 60_000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(then)
}

function activityFor(item: ExportSummary): {
  dateTime: string | null
  label: string
} {
  const syncedAt = item.last_inbound_sync_at
    ? Date.parse(item.last_inbound_sync_at)
    : Number.NaN
  const pushedAt = item.pushed_at ? Date.parse(item.pushed_at) : Number.NaN
  if (!Number.isNaN(syncedAt) && (Number.isNaN(pushedAt) || syncedAt >= pushedAt)) {
    return {
      dateTime: item.last_inbound_sync_at,
      label: `Synced ${formatWhen(item.last_inbound_sync_at) ?? "recently"}`,
    }
  }
  if (!Number.isNaN(pushedAt)) {
    return {
      dateTime: item.pushed_at,
      label: `Exported ${formatWhen(item.pushed_at) ?? "recently"}`,
    }
  }
  return {
    dateTime: null,
    label: item.status === "pending" ? "Sync queued" : "No sync activity",
  }
}

function ExportRow({ item }: { item: ExportSummary }) {
  const pct =
    item.total > 0
      ? Math.min(100, Math.max(0, Math.round((item.shipped / item.total) * 100)))
      : 0
  const tone = exportTone(
    item.status,
    item.out_of_sync,
    item.sync_paused,
    item.task_sync_status,
  )
  const activity = activityFor(item)
  const repoUrl = safeGitHubUrl(item.repo_url)
  const repoLabel = item.repo_full_name ?? item.workspace_name

  return (
    <article className={`ghx-row ghx-row-${tone}`}>
      <Link
        to={`/workspace/${item.workspace_id}/github`}
        className="ghx-row-primary"
        aria-label={`View ${item.workspace_name} GitHub export details`}
      >
        <span className={`ghx-row-mark ghx-row-mark-${tone}`} aria-hidden="true">
          <GitHubIcon />
        </span>
        <span className="ghx-row-main">
          <span className="ghx-row-name">{item.workspace_name}</span>
          {item.repo_full_name && (
            <span className="ghx-row-repo">{item.repo_full_name}</span>
          )}
        </span>
        <span className="ghx-row-progress">
          <span className="ghx-row-bar" aria-hidden="true">
            <span
              className={`ghx-row-bar-fill${pct === 100 && item.total > 0 ? " complete" : ""}`}
              style={{ width: `${pct}%` }}
            />
          </span>
          <span className="ghx-row-fraction">
            {item.total > 0
              ? `${item.shipped}/${item.total} shipped`
              : "No tracked issues"}
          </span>
        </span>
        <ExportStatusBadge
          status={item.status}
          outOfSync={item.out_of_sync}
          syncPaused={item.sync_paused}
          taskSyncStatus={item.task_sync_status}
          size="sm"
        />
        {activity.dateTime ? (
          <time className="ghx-row-when" dateTime={activity.dateTime}>
            {activity.label}
          </time>
        ) : (
          <span className="ghx-row-when">{activity.label}</span>
        )}
        <span className="ghx-row-chevron" aria-hidden="true">
          →
        </span>
      </Link>
      {repoUrl && (
        <a
          className="ghx-row-external"
          href={repoUrl}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${repoLabel} on GitHub in a new tab`}
          title="Open repository on GitHub"
        >
          <ExternalLinkIcon />
        </a>
      )}
    </article>
  )
}

function HubSkeleton() {
  return (
    <div className="ghx-hub-list" aria-busy="true" aria-label="Loading repositories">
      {[0, 1, 2].map((index) => (
        <div key={index} className="ghx-row ghx-row-skeleton" aria-hidden="true">
          <span className="ghx-row-primary">
            <span className="ghx-row-mark ghx-skeleton-block" />
            <span className="ghx-row-main">
              <span className="ghx-skel-line ghx-skel-name" />
              <span className="ghx-skel-line ghx-skel-repo" />
            </span>
            <span className="ghx-row-progress">
              <span className="ghx-skel-line ghx-skel-progress" />
              <span className="ghx-skel-line ghx-skel-progress-label" />
            </span>
            <span className="ghx-skel-line ghx-skel-badge" />
            <span className="ghx-skel-line ghx-skel-when" />
          </span>
        </div>
      ))}
    </div>
  )
}

export default function GitHubHub() {
  const navigate = useNavigate()
  const mountedRef = useRef(false)
  const requestInFlightRef = useRef(false)
  const [exports, setExports] = useState<ExportSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<GitHubHubFilter>("all")
  const [sort, setSort] = useState<GitHubHubSort>("recent")

  const loadExports = useCallback(async () => {
    if (requestInFlightRef.current) return
    requestInFlightRef.current = true
    if (mountedRef.current) setIsRefreshing(true)

    try {
      const rows = await listGitHubExports()
      if (!mountedRef.current) return
      setExports(rows)
      setError(null)
      setLastUpdatedAt(new Date().toISOString())
    } catch (err) {
      if (!mountedRef.current) return
      setExports((current) => current ?? [])
      setError(getApiErrorMessage(err, "Could not load your GitHub exports."))
    } finally {
      requestInFlightRef.current = false
      if (mountedRef.current) setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void loadExports()
    return () => {
      mountedRef.current = false
    }
  }, [loadExports])

  const rows = exports ?? []
  const summary = useMemo(() => summarizeGitHubExports(rows), [rows])
  const visibleRows = useMemo(
    () => selectGitHubExports(rows, query, filter, sort),
    [filter, query, rows, sort],
  )
  const syncingCount = useMemo(
    () => rows.filter((row) => row.status === "pending").length,
    [rows],
  )
  const hasPendingExport = syncingCount > 0

  useEffect(() => {
    if (!hasPendingExport) return
    const refreshPending = () => {
      if (document.visibilityState === "visible") void loadExports()
    }
    const intervalId = window.setInterval(
      refreshPending,
      PENDING_REFRESH_INTERVAL_MS,
    )
    document.addEventListener("visibilitychange", refreshPending)
    return () => {
      window.clearInterval(intervalId)
      document.removeEventListener("visibilitychange", refreshPending)
    }
  }, [hasPendingExport, loadExports])

  const loading = exports === null
  const hasActiveView = query.trim().length > 0 || filter !== "all"
  const updatedLabel = isRefreshing
    ? "Refreshing repositories…"
    : lastUpdatedAt
      ? `Updated ${formatWhen(lastUpdatedAt) ?? "just now"}`
      : ""

  const resetView = () => {
    setQuery("")
    setFilter("all")
  }

  return (
    <div className="ghx-page">
      <div className="ambient-field" aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
        <div className="ambient-band band-slate" />
      </div>

      <nav className="ghx-nav" aria-label="GitHub exports navigation">
        <div className="ghx-nav-inner ghx-nav-inner-hub">
          <button
            type="button"
            className="ghx-nav-back"
            onClick={() => navigate("/dashboard")}
            aria-label="Back to dashboard"
          >
            <span aria-hidden="true">←</span>
            Dashboard
          </button>
          <div className="ghx-nav-brand">
            <BrandLogo size="small" decorative />
            <span className="ghx-nav-divider">/</span>
            <span className="ghx-nav-section">Exports</span>
          </div>
          <span className="ghx-nav-grid-end" aria-hidden="true" />
        </div>
      </nav>

      <main className="ghx-main">
        <header className="ghx-hub-hero">
          <div className="ghx-hub-hero-copy">
            <span className="ghx-hub-eyebrow">GitHub</span>
            <h1 className="ghx-hub-title">Repository exports</h1>
            <p className="ghx-hub-subtitle">
              Track delivery across every exported workspace. Review issue
              progress, catch drift, and open the repository without losing
              your place.
            </p>
          </div>
          {!loading && summary.repositories > 0 && (
            <div className="ghx-hub-stats" aria-label="Exports summary">
              <div className="ghx-hub-stat">
                <span className="ghx-hub-stat-value">{summary.repositories}</span>
                <span className="ghx-hub-stat-label">
                  {summary.repositories === 1 ? "Repository" : "Repositories"}
                </span>
              </div>
              <div className="ghx-hub-stat">
                <span className="ghx-hub-stat-value">
                  {summary.shipped}
                  <span className="ghx-hub-stat-of">/{summary.total}</span>
                </span>
                <span className="ghx-hub-stat-label">Issues shipped</span>
              </div>
              {summary.attention > 0 ? (
                <button
                  type="button"
                  className="ghx-hub-stat ghx-hub-stat-action warn"
                  onClick={() => setFilter("attention")}
                  aria-pressed={filter === "attention"}
                >
                  <span className="ghx-hub-stat-value">{summary.attention}</span>
                  <span className="ghx-hub-stat-label">Need attention</span>
                </button>
              ) : (
                <div className="ghx-hub-stat">
                  <span className="ghx-hub-stat-value">0</span>
                  <span className="ghx-hub-stat-label">Need attention</span>
                </div>
              )}
            </div>
          )}
        </header>

        {error && (
          <div className="ghx-notice ghx-notice-error" role="alert">
            <span>{error}</span>
            <button
              type="button"
              className="ghx-notice-action"
              onClick={() => void loadExports()}
              disabled={isRefreshing}
            >
              Try again
            </button>
          </div>
        )}

        {loading ? (
          <HubSkeleton />
        ) : error && summary.repositories === 0 ? null : summary.repositories === 0 ? (
          <div className="ghx-empty">
            <span className="ghx-empty-mark" aria-hidden="true">
              <GitHubIcon />
            </span>
            <h2 className="ghx-empty-title">No repository exports yet</h2>
            <p className="ghx-empty-body">
              Finalise a workspace&apos;s Tasks, then export it to GitHub. Its
              repository and live issue progress will appear here.
            </p>
            <Link to="/dashboard" className="ghx-btn ghx-btn-primary">
              Choose a workspace
            </Link>
          </div>
        ) : (
          <section className="ghx-hub-results" aria-labelledby="ghx-results-title">
            <div className="ghx-hub-controls">
              <label className="ghx-search">
                <span className="ghx-visually-hidden">Search repositories</span>
                <SearchIcon />
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search workspaces or repositories"
                  autoComplete="off"
                />
              </label>

              <div
                className="ghx-filter-group"
                role="group"
                aria-label="Filter repositories"
              >
                <button
                  type="button"
                  className={filter === "all" ? "active" : ""}
                  onClick={() => setFilter("all")}
                  aria-pressed={filter === "all"}
                >
                  All <span>{summary.repositories}</span>
                </button>
                <button
                  type="button"
                  className={filter === "attention" ? "active" : ""}
                  onClick={() => setFilter("attention")}
                  aria-pressed={filter === "attention"}
                >
                  Attention <span>{summary.attention}</span>
                </button>
                <button
                  type="button"
                  className={filter === "syncing" ? "active" : ""}
                  onClick={() => setFilter("syncing")}
                  aria-pressed={filter === "syncing"}
                >
                  Syncing <span>{syncingCount}</span>
                </button>
              </div>

              <label className="ghx-sort">
                <span>Sort</span>
                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value as GitHubHubSort)}
                >
                  <option value="recent">Recent activity</option>
                  <option value="name">Workspace name</option>
                  <option value="progress">Issue progress</option>
                </select>
              </label>

              <button
                type="button"
                className={`ghx-refresh${isRefreshing ? " refreshing" : ""}`}
                onClick={() => void loadExports()}
                disabled={isRefreshing}
                aria-label={isRefreshing ? "Refreshing repositories" : "Refresh repositories"}
              >
                <RefreshIcon />
                <span>Refresh</span>
              </button>
            </div>

            <div className="ghx-results-meta">
              <h2 id="ghx-results-title">
                {visibleRows.length === 1
                  ? "1 repository"
                  : `${visibleRows.length} repositories`}
              </h2>
              <span className="ghx-updated" role="status" aria-live="polite">
                {updatedLabel}
              </span>
            </div>

            {visibleRows.length === 0 ? (
              <div className="ghx-empty ghx-empty-filtered">
                <h3 className="ghx-empty-title">No matching repositories</h3>
                <p className="ghx-empty-body">
                  Try a different search or clear the active filters.
                </p>
                {hasActiveView && (
                  <button type="button" className="ghx-btn ghx-btn-ghost" onClick={resetView}>
                    Clear search and filters
                  </button>
                )}
              </div>
            ) : (
              <div className="ghx-hub-list" aria-busy={isRefreshing}>
                {visibleRows.map((item) => (
                  <ExportRow key={item.push_id} item={item} />
                ))}
              </div>
            )}

            <div className="ghx-hub-footer">
              <span>Ready to ship another workspace?</span>
              <Link to="/dashboard">Open dashboard <span aria-hidden="true">→</span></Link>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}

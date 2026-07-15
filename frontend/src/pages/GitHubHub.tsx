import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"

import { BrandLogo } from "../components/shared/BrandLogo"
import {
  ExportStatusBadge,
  exportTone,
} from "../components/github/ExportStatusBadge"
import { GitHubIcon } from "../components/shared/icons"
import { getApiErrorMessage, listGitHubExports } from "../services/api"
import type { ExportSummary } from "../types/github"

function formatWhen(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const mins = Math.round((Date.now() - then) / 60000)
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

function ExportRow({ item }: { item: ExportSummary }) {
  const pct = item.total > 0 ? Math.round((item.shipped / item.total) * 100) : 0
  const tone = exportTone(
    item.status,
    item.out_of_sync,
    item.sync_paused,
    item.task_sync_status,
  )
  const when = formatWhen(item.pushed_at)

  return (
    <Link to={`/workspace/${item.workspace_id}/github`} className="ghx-row">
      <span className={`ghx-row-mark ghx-row-mark-${tone}`} aria-hidden="true">
        <GitHubIcon />
      </span>
      <div className="ghx-row-main">
        <span className="ghx-row-name">{item.workspace_name}</span>
        {item.repo_full_name && (
          <span className="ghx-row-repo">{item.repo_full_name}</span>
        )}
      </div>
      <div className="ghx-row-progress">
        <div className="ghx-row-bar" aria-hidden="true">
          <span
            className={`ghx-row-bar-fill${pct === 100 ? " complete" : ""}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="ghx-row-fraction">
          {item.shipped}/{item.total} shipped
        </span>
      </div>
      <ExportStatusBadge
        status={item.status}
        outOfSync={item.out_of_sync}
        syncPaused={item.sync_paused}
        taskSyncStatus={item.task_sync_status}
        size="sm"
      />
      <span className="ghx-row-when">{when ?? ""}</span>
      <span className="ghx-row-chevron" aria-hidden="true">
        →
      </span>
    </Link>
  )
}

export default function GitHubHub() {
  const navigate = useNavigate()
  const [exports, setExports] = useState<ExportSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setError(null)
    listGitHubExports()
      .then((rows) => {
        if (!cancelled) setExports(rows)
      })
      .catch((err) => {
        if (!cancelled) {
          setExports([])
          setError(getApiErrorMessage(err, "Could not load your GitHub exports."))
        }
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const summary = useMemo(() => {
    const rows = exports ?? []
    return {
      repos: rows.length,
      shipped: rows.reduce((n, r) => n + r.shipped, 0),
      total: rows.reduce((n, r) => n + r.total, 0),
      attention: rows.filter((r) => r.out_of_sync || r.sync_paused).length,
    }
  }, [exports])

  const loading = exports === null

  return (
    <div className="ghx-page">
      <div className="ambient-field" aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
        <div className="ambient-band band-slate" />
      </div>

      <nav className="ghx-nav">
        <div className="ghx-nav-inner">
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
          <span className="ghx-nav-spacer" aria-hidden="true" />
        </div>
      </nav>

      <main className="ghx-main">
        <header className="ghx-hub-hero">
          <div className="ghx-hub-hero-copy">
            <span className="ghx-hub-eyebrow">GitHub</span>
            <h1 className="ghx-hub-title">Exported repositories</h1>
            <p className="ghx-hub-subtitle">
              Every workspace you&apos;ve shipped to GitHub, and how far each one
              has been built out — issues created, closed, and drifting from the
              spec.
            </p>
          </div>
          {!loading && summary.repos > 0 && (
            <div className="ghx-hub-stats" aria-label="Exports summary">
              <div className="ghx-hub-stat">
                <span className="ghx-hub-stat-value">{summary.repos}</span>
                <span className="ghx-hub-stat-label">
                  {summary.repos === 1 ? "Repository" : "Repositories"}
                </span>
              </div>
              <div className="ghx-hub-stat">
                <span className="ghx-hub-stat-value">
                  {summary.shipped}
                  <span className="ghx-hub-stat-of">/{summary.total}</span>
                </span>
                <span className="ghx-hub-stat-label">Issues shipped</span>
              </div>
              <div className={`ghx-hub-stat${summary.attention > 0 ? " warn" : ""}`}>
                <span className="ghx-hub-stat-value">{summary.attention}</span>
                <span className="ghx-hub-stat-label">Need attention</span>
              </div>
            </div>
          )}
        </header>

        {error && (
          <div className="ghx-notice ghx-notice-error" role="alert">
            <span>{error}</span>
            <button
              type="button"
              className="ghx-notice-action"
              onClick={() => setReloadKey((k) => k + 1)}
            >
              Try again
            </button>
          </div>
        )}

        {loading ? (
          <div className="ghx-hub-list" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="ghx-row ghx-row-skeleton">
                <span className="ghx-row-mark" />
                <span className="ghx-skel-line" />
              </div>
            ))}
          </div>
        ) : error ? null : summary.repos === 0 ? (
          <div className="ghx-empty">
            <span className="ghx-empty-mark" aria-hidden="true">
              <GitHubIcon />
            </span>
            <h2 className="ghx-empty-title">No exports yet</h2>
            <p className="ghx-empty-body">
              Once you finalise a workspace&apos;s Tasks and push it to GitHub,
              its repository shows up here with live issue tracking.
            </p>
            <Link to="/dashboard" className="ghx-btn ghx-btn-primary">
              Go to workspaces
            </Link>
          </div>
        ) : (
          <div className="ghx-hub-list">
            {(exports ?? []).map((item) => (
              <ExportRow key={item.push_id} item={item} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

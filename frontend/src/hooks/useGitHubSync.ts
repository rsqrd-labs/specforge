import { useCallback, useEffect, useRef, useState } from "react"

import {
  getGitHubInstallations,
  getGitHubPush,
  getGitHubSync,
  backfillWorkspace,
  resyncWorkspace,
} from "../services/api"
import type { SyncConnection } from "../components/workspace/TaskCompletionPanel"
import type { SyncState } from "../types/github"

/** Only the cheap, database-backed sync view is polled at this cadence. Repo and
 * installation metadata are fetched once, avoiding the former three-request
 * poll while reducing worst-case visible webhook latency from 15s to 5s. */
const POLL_INTERVAL_MS = 5_000
const REFRESH_POLL_INTERVAL_MS = 1_000
const REFRESH_TIMEOUT_MS = 45_000

export interface GitHubSyncState {
  data: SyncState | null
  repoFullName: string | null
  repoUrl: string | null
  connection: SyncConnection
  loading: boolean
  resyncing: boolean
  resync: () => Promise<void>
  refreshing: boolean
  refreshError: string | null
  refreshFromGitHub: () => Promise<boolean>
}

/**
 * Drives the {@link TaskCompletionPanel}: fetches the workspace's live GitHub
 * sync state, the repo coordinates (for issue deep-links), and the install
 * status (to detect a suspended/removed App), then polls so a task closing on
 * GitHub flips to "shipped" here without a manual refresh.
 *
 * `enabled` gates the whole thing (only the Tasks stage needs it), so other
 * stages issue zero GitHub requests.
 */
export function useGitHubSync(
  workspaceId: string | undefined,
  enabled: boolean,
): GitHubSyncState {
  const [data, setData] = useState<SyncState | null>(null)
  const [repoFullName, setRepoFullName] = useState<string | null>(null)
  const [repoUrl, setRepoUrl] = useState<string | null>(null)
  const [connection, setConnection] = useState<SyncConnection>("connected")
  const [loading, setLoading] = useState(true)
  const [resyncing, setResyncing] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refreshSync = useCallback(async () => {
    if (!workspaceId) return
    const sync = await getGitHubSync(workspaceId).catch(() => null)
    if (mounted.current) setData(sync)
    return sync
  }, [workspaceId])

  const refresh = useCallback(async () => {
    if (!workspaceId) return
    // Metadata tolerates its own failure: a never-pushed workspace 404s and an
    // unconfigured App yields no installations. Polls below only fetch sync.
    const [sync, push, installs] = await Promise.all([
      getGitHubSync(workspaceId).catch(() => null),
      getGitHubPush(workspaceId).catch(() => null),
      getGitHubInstallations().catch(() => ({
        installations: [],
        on_legacy_oauth: false,
      })),
    ])
    if (!mounted.current) return
    setData(sync)
    setRepoFullName(push?.repo_full_name ?? null)
    setRepoUrl(push?.repo_url ?? null)
    const active = installs.installations.filter((i) => !i.suspended)
    setConnection(
      active.length > 0
        ? "connected"
        : installs.installations.length > 0
          ? "suspended"
          : "disconnected",
    )
    setLoading(false)
  }, [workspaceId])

  useEffect(() => {
    if (!enabled || !workspaceId) return undefined
    setLoading(true)
    void refresh()
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshSync()
    }, POLL_INTERVAL_MS)
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void refreshSync()
    }
    document.addEventListener("visibilitychange", onVisibilityChange)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  }, [enabled, workspaceId, refresh, refreshSync])

  const resync = useCallback(async () => {
    if (!workspaceId) return
    setResyncing(true)
    try {
      await resyncWorkspace(workspaceId)
      await refresh()
    } finally {
      if (mounted.current) setResyncing(false)
    }
  }, [workspaceId, refresh])

  const refreshFromGitHub = useCallback(async () => {
    if (!workspaceId || refreshing) return false
    setRefreshing(true)
    setRefreshError(null)
    try {
      const accepted = await backfillWorkspace(workspaceId)
      const requestedAt = Date.parse(accepted.requested_at)
      const deadline = Date.now() + REFRESH_TIMEOUT_MS
      while (mounted.current && Date.now() < deadline) {
        const next = await refreshSync()
        const completedAt = next?.last_inbound_sync_at
          ? Date.parse(next.last_inbound_sync_at)
          : Number.NaN
        if (Number.isFinite(completedAt) && completedAt >= requestedAt) {
          if (next?.last_inbound_sync_error === "installation_unavailable") {
            await refresh()
            setRefreshError(
              "GitHub access was removed. Reconnect GitHub to resume sync.",
            )
            return false
          }
          return true
        }
        await new Promise<void>((resolve) =>
          window.setTimeout(resolve, REFRESH_POLL_INTERVAL_MS),
        )
      }
      if (!mounted.current) return false
      throw new Error("GitHub refresh did not complete in time")
    } catch {
      if (mounted.current) {
        setRefreshError("GitHub did not finish checking. Try again in a moment.")
      }
      return false
    } finally {
      if (mounted.current) setRefreshing(false)
    }
  }, [workspaceId, refreshing, refresh, refreshSync])

  return {
    data,
    repoFullName,
    repoUrl,
    connection,
    loading,
    resyncing,
    resync,
    refreshing,
    refreshError,
    refreshFromGitHub,
  }
}

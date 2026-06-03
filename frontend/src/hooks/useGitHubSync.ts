import { useCallback, useEffect, useRef, useState } from "react"

import {
  getGitHubInstallations,
  getGitHubPush,
  getGitHubSync,
  resyncWorkspace,
} from "../services/api"
import type { SyncConnection } from "../components/workspace/TaskCompletionPanel"
import type { SyncState } from "../types/github"

/** Poll cadence for the "live" feeling — gentle, and only while the tab is
 *  visible so a backgrounded workspace makes no requests. */
const POLL_INTERVAL_MS = 15_000

export interface GitHubSyncState {
  data: SyncState | null
  repoFullName: string | null
  repoUrl: string | null
  connection: SyncConnection
  loading: boolean
  resyncing: boolean
  resync: () => Promise<void>
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

  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    if (!workspaceId) return
    // Each fetch tolerates its own failure: a never-pushed workspace 404s on
    // sync (→ null), and an unconfigured App yields no installations. None of
    // these are errors the panel should surface as a crash.
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
      if (document.visibilityState === "visible") void refresh()
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [enabled, workspaceId, refresh])

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

  return { data, repoFullName, repoUrl, connection, loading, resyncing, resync }
}

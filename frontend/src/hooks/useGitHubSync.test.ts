import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  backfillWorkspace,
  getGitHubInstallations,
  getGitHubPush,
  getGitHubSync,
  resyncWorkspace,
} from "../services/api"
import type { SyncState } from "../types/github"
import { useGitHubSync } from "./useGitHubSync"

vi.mock("../services/api", () => ({
  backfillWorkspace: vi.fn(),
  getGitHubInstallations: vi.fn(),
  getGitHubPush: vi.fn(),
  getGitHubSync: vi.fn(),
  resyncWorkspace: vi.fn(),
}))

const syncState = (
  lastInboundSyncAt: string | null,
  lastInboundSyncError: SyncState["last_inbound_sync_error"] = null,
): SyncState => ({
  push_id: "push-1",
  status: "completed",
  task_sync_status: "up_to_date",
  sync_paused: false,
  out_of_sync: false,
  shipped: 0,
  total: 1,
  last_inbound_sync_at: lastInboundSyncAt,
  last_inbound_sync_error: lastInboundSyncError,
  tasks: [
    {
      task_ref: "task-1",
      issue_number: 1,
      state: "open",
      done_via: null,
      done_at: null,
      synced_at: null,
      human_ref: "T-001",
      title: "Ship it",
    },
  ],
})

describe("useGitHubSync", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getGitHubPush).mockResolvedValue({
      push_id: "push-1",
      status: "completed",
      repo_full_name: "octo/spec",
      repo_url: "https://github.com/octo/spec",
      issue_count: 1,
      installation_id: "install-1",
      pushed_at: null,
    })
    vi.mocked(getGitHubInstallations).mockResolvedValue({
      installations: [
        {
          id: "install-1",
          installation_id: 1,
          account_login: "octo",
          account_type: "User",
          repository_selection: "all",
          suspended: false,
        },
      ],
      on_legacy_oauth: false,
    })
    vi.mocked(backfillWorkspace).mockResolvedValue({
      push_id: "push-1",
      requested_at: "2026-07-16T00:00:00Z",
    })
  })
  afterEach(() => vi.useRealTimers())

  it("requests a coalesced GitHub reconciliation when the Tasks screen opens", async () => {
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))

    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))

    await waitFor(() =>
      expect(backfillWorkspace).toHaveBeenCalledWith("workspace-1", true),
    )
  })

  it("keeps a manual check pending until the worker completion marker advances", async () => {
    const requestedAt = "2026-07-16T00:00:05Z"
    let finishPoll: ((value: SyncState) => void) | undefined
    vi.mocked(getGitHubSync)
      .mockResolvedValueOnce(syncState(null))
      .mockImplementationOnce(
        () =>
          new Promise<SyncState>((resolve) => {
            finishPoll = resolve
          }),
      )
    vi.mocked(backfillWorkspace).mockResolvedValue({
      push_id: "push-1",
      requested_at: requestedAt,
    })

    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))

    let completed: boolean | undefined
    let refreshPromise: Promise<void> | undefined
    act(() => {
      refreshPromise = result.current.refreshFromGitHub().then((value) => {
        completed = value
      })
    })
    await waitFor(() => expect(result.current.refreshing).toBe(true))

    await act(async () => {
      finishPoll?.(syncState("2026-07-16T00:00:06Z"))
      await refreshPromise
    })

    expect(completed).toBe(true)
    expect(result.current.refreshing).toBe(false)
    expect(result.current.refreshError).toBeNull()
  })

  it("surfaces a removed installation immediately instead of waiting for retries", async () => {
    const requestedAt = "2026-07-16T00:00:05Z"
    const unavailable = syncState(
      "2026-07-16T00:00:06Z",
      "installation_unavailable",
    )
    vi.mocked(getGitHubSync)
      .mockResolvedValueOnce(syncState(null))
      .mockResolvedValue(unavailable)
    vi.mocked(backfillWorkspace).mockResolvedValue({
      push_id: "push-1",
      requested_at: requestedAt,
    })

    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    vi.mocked(getGitHubInstallations).mockResolvedValue({
      installations: [
        {
          id: "install-1",
          installation_id: 1,
          account_login: "octo",
          account_type: "User",
          repository_selection: "all",
          suspended: true,
        },
      ],
      on_legacy_oauth: false,
    })

    let completed = true
    await act(async () => {
      completed = await result.current.refreshFromGitHub()
    })

    expect(completed).toBe(false)
    expect(result.current.connection).toBe("suspended")
    expect(result.current.refreshError).toMatch(/reconnect github/i)
  })

  it("is inert without an enabled workspace", async () => {
    const { result } = renderHook(() => useGitHubSync(undefined, false))
    await act(async () => result.current.resync())
    await expect(result.current.refreshFromGitHub()).resolves.toBe(false)
    expect(getGitHubSync).not.toHaveBeenCalled()
  })

  it("degrades failed metadata to a disconnected empty state", async () => {
    vi.mocked(getGitHubSync).mockRejectedValue(new Error("offline"))
    vi.mocked(getGitHubPush).mockRejectedValue(new Error("offline"))
    vi.mocked(getGitHubInstallations).mockRejectedValue(new Error("offline"))
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current).toMatchObject({ data: null, repoFullName: null, repoUrl: null, connection: "disconnected" })
  })

  it("classifies a suspended installation without an active peer", async () => {
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    vi.mocked(getGitHubInstallations).mockResolvedValue({
      installations: [{ id: "i", installation_id: 1, account_login: "octo", account_type: "User", repository_selection: "all", suspended: true }],
      on_legacy_oauth: false,
    })
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.connection).toBe("suspended")
  })

  it("resyncs and refreshes metadata", async () => {
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    vi.mocked(resyncWorkspace).mockResolvedValue({ push_id: "push-1", status: "pending" } as never)
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(async () => result.current.resync())
    expect(resyncWorkspace).toHaveBeenCalledWith("workspace-1")
    expect(result.current.resyncing).toBe(false)
  })

  it("reports an explicit backfill failure", async () => {
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    vi.mocked(backfillWorkspace)
      .mockResolvedValueOnce({ push_id: "push-1", requested_at: "2026-01-01T00:00:00Z" })
      .mockRejectedValueOnce(new Error("offline"))
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    let completed = true
    await act(async () => { completed = await result.current.refreshFromGitHub() })
    expect(completed).toBe(false)
    expect(result.current.refreshError).toMatch(/did not finish/i)
  })

  it("coalesces a second manual refresh while one is active", async () => {
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    let accept!: (value: { push_id: string; requested_at: string }) => void
    vi.mocked(backfillWorkspace).mockImplementationOnce(() => new Promise((resolve) => { accept = resolve }))
    let first!: Promise<boolean>
    act(() => { first = result.current.refreshFromGitHub() })
    await waitFor(() => expect(result.current.refreshing).toBe(true))
    await expect(result.current.refreshFromGitHub()).resolves.toBe(false)
    await act(async () => {
      vi.mocked(getGitHubSync).mockResolvedValue(syncState("2026-01-01T00:00:01Z"))
      accept({ push_id: "push-1", requested_at: "2026-01-01T00:00:00Z" })
      await first
    })
  })

  it("polls only while visible and refreshes immediately on visibility return", async () => {
    vi.useFakeTimers()
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" })
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    const calls = vi.mocked(getGitHubSync).mock.calls.length
    await act(async () => vi.advanceTimersByTimeAsync(30_000))
    expect(getGitHubSync).toHaveBeenCalledTimes(calls)
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" })
    await act(async () => document.dispatchEvent(new Event("visibilitychange")))
    expect(vi.mocked(getGitHubSync).mock.calls.length).toBeGreaterThan(calls)
    expect(result.current.loading).toBe(false)
  })

  it("drops metadata and poll results that settle after unmount", async () => {
    let resolveSync!: (value: SyncState) => void
    vi.mocked(getGitHubSync).mockImplementation(() => new Promise((resolve) => { resolveSync = resolve }))
    const { unmount } = renderHook(() => useGitHubSync("workspace-1", true))
    unmount()
    await act(async () => resolveSync(syncState(null)))
  })

  it("does not update resync state after unmount", async () => {
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    let finish!: () => void
    vi.mocked(resyncWorkspace).mockImplementation(() => new Promise((resolve) => { finish = () => resolve({} as never) }))
    const { result, unmount } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    let pending!: Promise<void>
    act(() => { pending = result.current.resync() })
    unmount()
    await act(async () => { finish(); await pending })
  })

  it("stops a manual refresh cleanly after unmount", async () => {
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    const { result, unmount } = renderHook(() => useGitHubSync("workspace-1", true))
    await waitFor(() => expect(result.current.loading).toBe(false))
    vi.mocked(backfillWorkspace).mockResolvedValueOnce({ push_id: "p", requested_at: new Date().toISOString() })
    let pending!: Promise<boolean>
    act(() => { pending = result.current.refreshFromGitHub() })
    unmount()
    await expect(pending).resolves.toBe(false)
  })

  it("turns a failed lightweight poll into an empty sync state", async () => {
    vi.useFakeTimers()
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    vi.mocked(getGitHubSync).mockRejectedValue(new Error("offline"))
    await act(async () => vi.advanceTimersByTimeAsync(5_000))
    expect(result.current.data).toBeNull()
  })

  it("times out a manual refresh whose worker marker never advances", async () => {
    vi.useFakeTimers()
    vi.mocked(getGitHubSync).mockResolvedValue(syncState(null))
    const { result } = renderHook(() => useGitHubSync("workspace-1", true))
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    vi.mocked(backfillWorkspace).mockResolvedValueOnce({ push_id: "p", requested_at: new Date().toISOString() })
    let pending!: Promise<boolean>
    act(() => { pending = result.current.refreshFromGitHub() })
    await act(async () => vi.advanceTimersByTimeAsync(46_000))
    await expect(pending).resolves.toBe(false)
    expect(result.current.refreshError).toMatch(/did not finish/i)
  })
})

import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  backfillWorkspace,
  getGitHubInstallations,
  getGitHubPush,
  getGitHubSync,
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
})

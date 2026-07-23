import { afterEach, describe, expect, it, vi } from "vitest"

import {
  api,
  createIncrement,
  getGitHubInstallUrl,
  getGitHubInstallations,
  getGitHubRepositories,
  getGitHubSync,
  listIncrements,
  resyncWorkspace,
} from "./api"

// Behavioral coverage for the Phase-21 (T-275) GitHub living-integration client
// functions, beyond the structural string-match contract. The invariant under
// test: a never-pushed / stale / App-disabled workspace is a *normal* empty
// state, so the read fetchers map the expected 404/503 to a safe value and only
// real failures propagate.

function axiosError(status: number): unknown {
  // Shape that axios.isAxiosError recognises (isAxiosError === true).
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true,
    response: { status },
  })
}

describe("GitHub living-integration api client", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("getGitHubSync maps a 404 (never pushed / stale) to null, not a throw", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce(axiosError(404))
    await expect(getGitHubSync("ws-1")).resolves.toBeNull()
  })

  it("getGitHubSync returns the live sync state on success", async () => {
    vi.spyOn(api, "get").mockResolvedValueOnce({
      data: {
        push_id: "push-1",
        status: "completed",
        task_sync_status: "changes_pending",
        sync_paused: false,
        out_of_sync: true,
        shipped: 1,
        total: 2,
        tasks: [],
      },
    })
    const state = await getGitHubSync("ws-1")
    expect(state?.out_of_sync).toBe(true)
    expect(state?.shipped).toBe(1)
  })

  it("getGitHubSync re-throws a non-404 error (it does not swallow real failures)", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce(axiosError(500))
    await expect(getGitHubSync("ws-1")).rejects.toThrow()
  })

  it("getGitHubInstallations maps a 404 to the empty, non-legacy state", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce(axiosError(404))
    const result = await getGitHubInstallations()
    expect(result.installations).toEqual([])
    expect(result.on_legacy_oauth).toBe(false)
  })

  it("getGitHubInstallUrl maps a 503 (App not configured) to null, not a throw", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce(axiosError(503))
    await expect(getGitHubInstallUrl()).resolves.toBeNull()
  })

  it("getGitHubInstallUrl returns the install URL on success", async () => {
    vi.spyOn(api, "get").mockResolvedValueOnce({
      data: { url: "https://github.com/apps/thought2build/installations/new" },
    })
    await expect(getGitHubInstallUrl()).resolves.toContain("/installations/new")
  })

  it("listIncrements maps a 404 to an empty timeline", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce(axiosError(404))
    await expect(listIncrements("ws-1")).resolves.toEqual([])
  })

  it("getGitHubRepositories returns the repo-picker feed on success", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValueOnce({
      data: {
        repositories: [
          {
            id: 1,
            name: "alpha",
            full_name: "octo/alpha",
            private: true,
            html_url: "https://github.com/octo/alpha",
          },
        ],
        truncated: false,
        can_create: true,
      },
    })
    const list = await getGitHubRepositories("inst-1")
    expect(list.repositories).toHaveLength(1)
    expect(list.can_create).toBe(true)
    expect(String(get.mock.calls[0][0])).toBe(
      "/integrations/github/installations/inst-1/repos",
    )
  })

  it("getGitHubRepositories propagates failures — a fetch error is NOT an empty list", async () => {
    // Unlike getGitHubInstallations there is deliberately no graceful-empty:
    // the modal must distinguish "no repos" (add-on-GitHub state) from "fetch
    // failed" (retry + manual name entry).
    vi.spyOn(api, "get").mockRejectedValueOnce(axiosError(502))
    await expect(getGitHubRepositories("inst-1")).rejects.toThrow()
  })

  it("resyncWorkspace POSTs the resync endpoint and returns the pending push", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockResolvedValueOnce({ data: { id: "push-2", status: "pending" } })
    const push = await resyncWorkspace("ws-9")
    expect(push.status).toBe("pending")
    expect(String(post.mock.calls[0][0])).toBe("/workspaces/ws-9/sync/resync")
  })

  it("createIncrement POSTs the feature request to the increments endpoint", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValueOnce({
      data: {
        id: "inc-1",
        sequence: 1,
        title: "Add billing",
        status: "ready",
        new_task_count: 3,
      },
    })
    const inc = await createIncrement("ws-9", {
      feature_request: "Add a billing page with Stripe checkout",
    })
    expect(inc.title).toBe("Add billing")
    expect(inc.new_task_count).toBe(3)
    const [url, body] = post.mock.calls[0]
    expect(String(url)).toBe("/workspaces/ws-9/increments")
    expect(body).toEqual({
      feature_request: "Add a billing page with Stripe checkout",
    })
  })
})

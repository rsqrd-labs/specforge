import axios from "axios"
import { AxiosHeaders, type AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from "axios"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import * as client from "./api"

const payload = { marker: "server-payload" }

describe("authenticated API endpoint contracts", () => {
  beforeEach(() => {
    vi.spyOn(client.api, "get").mockResolvedValue({ data: payload })
    vi.spyOn(client.api, "post").mockResolvedValue({ data: payload })
    vi.spyOn(client.api, "patch").mockResolvedValue({ data: payload })
    vi.spyOn(client.api, "delete").mockResolvedValue({ data: payload })
  })

  afterEach(() => vi.restoreAllMocks())

  it("maps workspace lifecycle calls to their owner-scoped endpoints", async () => {
    await client.getWorkspaces()
    await client.createWorkspace({ name: "New", problem_statement: "A complete problem" })
    await client.getWorkspace("ws")
    await client.updateWorkspace("ws", { name: "Renamed" })
    await client.setWorkspaceCritic("ws", true)
    await client.setWorkspaceResearch("ws", true)
    await client.deleteWorkspace("ws", "retention-v1")
    await client.deleteWorkspace("legacy")
    await client.restoreWorkspace("ws")
    await client.listTrashedWorkspaces()
    await client.getRetentionPolicy()

    expect(client.api.get).toHaveBeenCalledWith("/workspaces")
    expect(client.api.post).toHaveBeenCalledWith("/workspaces", {
      name: "New",
      problem_statement: "A complete problem",
    })
    expect(client.api.patch).toHaveBeenCalledWith("/workspaces/ws/critic", {
      disable_critic: true,
    })
    expect(client.api.patch).toHaveBeenCalledWith("/workspaces/ws/research", {
      brave_research_enabled: true,
    })
    expect(client.api.delete).toHaveBeenCalledWith("/workspaces/ws", {
      params: { ack_version: "retention-v1" },
    })
    expect(client.api.delete).toHaveBeenCalledWith("/workspaces/legacy", {
      params: undefined,
    })
  })

  it("maps stage state transitions and preserves their concurrency payloads", async () => {
    await client.getStage("stage")
    await client.getStageGeneration("stage")
    await client.cancelStageGeneration("stage", "generation")
    await client.refineStage("stage", {
      instruction: "Make it safer",
      selection_start: 0,
      selection_end: 4,
      selected_text: "text",
    })
    await client.finaliseStage("stage")
    await client.acknowledgeStaleStage("stage")
    await client.rollbackStage("stage", 3)
    await client.getStageVersions("stage")
    await client.getStageEval("stage")
    await client.revalidateTasks("stage")
    await client.acceptStageDiff("stage", "replacement", 2)
    await client.rejectStageDiff("stage")
    await client.updateStageContent("stage", "edited")
    await client.acknowledgeReviewGate("stage")
    await client.overrideQualityGate("stage")

    expect(client.api.post).toHaveBeenCalledWith(
      "/stages/stage/generation/cancel",
      { generation_id: "generation" },
    )
    expect(client.api.post).toHaveBeenCalledWith("/stages/stage/rollback", {
      version_number: 3,
    })
    expect(client.api.post).toHaveBeenCalledWith("/stages/stage/accept-diff", {
      proposed_content: "replacement",
      base_version: 2,
    })
    expect(client.api.patch).toHaveBeenCalledWith("/stages/stage/content", {
      content: "edited",
    })
  })

  it("constructs stream URLs without starting an accidental duplicate request", async () => {
    await expect(client.generateStage("s")).resolves.toEqual({
      stage_id: "s",
      stream_url: "/stages/s/generate",
    })
    await expect(client.regenerateStage("s")).resolves.toMatchObject({
      stream_url: "/stages/s/regenerate",
    })
    await expect(client.regenerateStageForGaps("s")).resolves.toMatchObject({
      stream_url: "/stages/s/regenerate-gaps",
    })
    expect(client.api.post).not.toHaveBeenCalled()
  })

  it("requests export bytes with explicit response types and long PDF timeout", async () => {
    const blob = new Blob(["artifact"])
    vi.mocked(client.api.get).mockResolvedValue({ data: blob })
    vi.mocked(client.api.post).mockResolvedValue({ data: blob })
    await client.exportWorkspace("ws")
    await client.downloadAgentInstructions("ws", "both")
    await client.exportWorkspacePdf("ws")

    expect(client.api.post).toHaveBeenCalledWith("/workspaces/ws/export", undefined, {
      responseType: "blob",
    })
    expect(client.api.get).toHaveBeenCalledWith(
      "/workspaces/ws/export/agent-instructions/both",
      { responseType: "blob" },
    )
    expect(client.api.post).toHaveBeenCalledWith(
      "/workspaces/ws/export/pdf",
      undefined,
      { responseType: "blob", timeout: client.LLM_SYNC_API_TIMEOUT_MS },
    )
  })

  it("maps sharing, clarification, credit, and billing operations", async () => {
    await client.enablePublicShare("ws")
    await client.rotatePublicShare("ws")
    await client.disablePublicShare("ws")
    vi.mocked(client.api.post).mockResolvedValueOnce({
      status: 200,
      data: { questions: [{ question: "Who?", why_it_matters: "Scope" }] },
    })
    await expect(client.requestClarification("ws")).resolves.toMatchObject({
      questions: expect.any(Array),
    })
    await client.persistClarification(
      "ws",
      [{ question: "Who?", answer: "Teams" }],
      "existing",
    )
    await client.getCredits()
    await client.fetchBillingPackage()
    await client.createCheckoutSession()
    await client.fetchBillingStatus("checkout")
    await client.fetchBillingHistory()

    expect(client.api.patch).toHaveBeenCalledWith("/workspaces/ws/clarify", {
      answers: [{ question: "Who?", answer: "Teams" }],
      mode: "existing",
    })
    expect(client.api.get).toHaveBeenCalledWith("/billing/status", {
      params: { checkout_ref: "checkout" },
    })
  })

  it("maps GitHub ownership, export, sync, increment, and idea operations", async () => {
    const controller = new AbortController()
    await client.getGitHubIntegration()
    await client.deleteGitHubIntegration()
    await client.exportWorkspaceToGitHub(
      "ws",
      { repo_name: "repo", visibility: "private" },
      controller.signal,
    )
    await client.getGitHubPush("ws")
    await client.getGitHubInstallUrl()
    await client.getGitHubInstallations()
    await client.getGitHubRepositories("installation")
    await client.revokeGitHubInstallation("installation")
    await client.getGitHubSync("ws")
    await client.listGitHubExports()
    await client.resyncWorkspace("ws")
    await client.backfillWorkspace("ws")
    await client.backfillWorkspace("ws", true)
    await client.listIncrements("ws")
    await client.createIncrement("ws", { feature_request: "Add a reliable audit feed" })
    await client.pushIncrement("ws", "increment")
    await client.listIdeas("ws")
    await client.createIdea("ws", { text: "Add exports" })

    expect(client.api.post).toHaveBeenCalledWith(
      "/workspaces/ws/export/github",
      { repo_name: "repo", visibility: "private" },
      { signal: controller.signal },
    )
    expect(client.api.post).toHaveBeenCalledWith(
      "/workspaces/ws/sync/backfill",
      null,
      { params: { automatic: true } },
    )
    expect(client.api.post).toHaveBeenCalledWith(
      "/workspaces/ws/increments",
      { feature_request: "Add a reliable audit feed" },
      { timeout: client.LLM_SYNC_API_TIMEOUT_MS },
    )
  })

  it("maps every owner Storyboard operation including both notes variants", async () => {
    await client.listStoryboards("ws")
    await client.getLatestStoryboard("ws")
    await client.generateStoryboard("ws")
    await client.getStoryboard("story")
    await client.regenerateStoryboard("story")
    await client.regenerateStoryboardSection("story", "section")
    await client.getStoryboardPresenter("story")
    await client.downloadStoryboard("story", "notes", "pdf")
    await client.downloadStoryboard("story", "pdf")
    await client.shareStoryboard("story")
    await client.shareStoryboard("story", { allow_pdf_download: true })
    await client.disableStoryboardShare("story")
    await client.rotateStoryboardShare("story")

    expect(client.api.get).toHaveBeenCalledWith("/storyboards/story/download/notes", {
      responseType: "blob",
      params: { format: "pdf" },
    })
    expect(client.api.get).toHaveBeenCalledWith("/storyboards/story/download/pdf", {
      responseType: "blob",
      params: undefined,
    })
    expect(client.api.post).toHaveBeenCalledWith("/storyboards/story/share", {})
  })
})

describe("authentication helper contracts", () => {
  afterEach(() => {
    client.setAccessToken(null)
    vi.restoreAllMocks()
  })

  it("attaches bearer identity only when a token exists", () => {
    const config = {
      headers: new AxiosHeaders(),
      method: "get",
      url: "/auth/me",
    } as InternalAxiosRequestConfig
    expect(client.attachAuthorizationHeader(config, null)).toBe(config)
    const authorized = client.attachAuthorizationHeader(config, "token")
    expect(AxiosHeaders.from(authorized.headers).get("Authorization")).toBe(
      "Bearer token",
    )
  })

  it("classifies retry eligibility using both status and the replay guard", () => {
    expect(
      client.shouldAttemptRefresh({
        response: { status: 401 },
        config: { headers: new AxiosHeaders() },
      } as unknown as AxiosError),
    ).toBe(true)
    expect(
      client.shouldAttemptRefresh({
        response: { status: 500 },
        config: { headers: new AxiosHeaders() },
      } as unknown as AxiosError),
    ).toBe(false)
    expect(
      client.shouldAttemptRefresh({
        response: { status: 401 },
        config: { headers: new AxiosHeaders(), _retry: true },
      } as unknown as AxiosError),
    ).toBe(false)
  })

  it("replays a 401 once through a supplied refresh client", async () => {
    const replay = vi.fn().mockResolvedValue({ data: payload })
    const refresh = {
      post: vi.fn().mockResolvedValue({ data: { accessToken: "camel-token" } }),
    }
    const error = {
      response: { status: 401 },
      config: { headers: new AxiosHeaders(), method: "get", url: "/workspaces" },
    } as AxiosError

    await client.handleUnauthorizedResponse(
      error,
      replay as unknown as AxiosInstance,
      refresh as unknown as AxiosInstance,
    )
    expect(refresh.post).toHaveBeenCalledWith("/auth/refresh")
    expect(replay).toHaveBeenCalledTimes(1)
    expect(client.getAccessToken()).toBe("camel-token")
  })

  it("rejects a non-retryable response and failed or empty refreshes", async () => {
    const replay = vi.fn()
    const nonRetryable = { response: { status: 403 } } as AxiosError
    await expect(
      client.handleUnauthorizedResponse(
        nonRetryable,
        replay as unknown as AxiosInstance,
        { post: vi.fn() } as unknown as AxiosInstance,
      ),
    ).rejects.toBe(nonRetryable)

    const original = {
      response: { status: 401 },
      config: { headers: new AxiosHeaders(), method: "get", url: "/workspaces" },
    } as AxiosError
    await expect(
      client.handleUnauthorizedResponse(
        original,
        replay as unknown as AxiosInstance,
        { post: vi.fn().mockResolvedValue({ data: {} }) } as unknown as AxiosInstance,
      ),
    ).rejects.toBe(original)

    const refreshFailure = new Error("refresh offline")
    const nextAttempt = {
      response: { status: 401 },
      config: { headers: new AxiosHeaders(), method: "get", url: "/workspaces" },
    } as AxiosError
    await expect(
      client.handleUnauthorizedResponse(
        nextAttempt,
        replay as unknown as AxiosInstance,
        {
          post: vi.fn().mockRejectedValue(refreshFailure),
        } as unknown as AxiosInstance,
      ),
    ).rejects.toBe(refreshFailure)
  })

  it("reads the current user with an established in-memory session", async () => {
    client.setAccessToken("session-token")
    const get = vi.spyOn(client.api, "get").mockResolvedValue({ data: payload })
    await expect(client.getCurrentUser()).resolves.toBe(payload)
    expect(get).toHaveBeenCalledWith("/auth/me")
  })
})

describe("public API isolation and graceful fallbacks", () => {
  afterEach(() => vi.restoreAllMocks())

  it("uses bare Axios for public workspace reads", async () => {
    const get = vi.spyOn(axios, "get").mockResolvedValue({ data: payload })
    await expect(client.getPublicWorkspace("slug")).resolves.toBe(payload)
    expect(get).toHaveBeenCalledWith(expect.stringContaining("/public/slug"))
  })

  it("returns an empty template catalog when the public catalog fails", async () => {
    vi.spyOn(axios, "get").mockRejectedValue(new Error("offline"))
    await expect(client.getTemplates(true)).resolves.toEqual([])
  })

  it("caches a successful template catalog unless force-refresh is requested", async () => {
    const catalog = [{ id: "tpl" }]
    const get = vi.spyOn(axios, "get").mockResolvedValue({ data: catalog })
    await expect(client.getTemplates(true)).resolves.toBe(catalog)
    await expect(client.getTemplates()).resolves.toBe(catalog)
    expect(get).toHaveBeenCalledTimes(1)
    await client.getTemplates(true)
    expect(get).toHaveBeenCalledTimes(2)
  })

  it("handles empty and unavailable advisory responses without blocking generation", async () => {
    vi.spyOn(client.api, "get").mockResolvedValue({ data: { estimates: null } })
    await expect(client.fetchGenerationEstimates()).resolves.toEqual([])
    vi.mocked(client.api.get).mockResolvedValueOnce({ data: undefined })
    await expect(client.fetchGenerationEstimates()).resolves.toEqual([])
    vi.mocked(client.api.get).mockRejectedValueOnce(new Error("offline"))
    await expect(client.fetchGenerationEstimates()).resolves.toEqual([])

    vi.spyOn(client.api, "post").mockResolvedValue({ status: 204, data: undefined })
    await expect(client.requestClarification("ws")).resolves.toBeNull()
  })

  it("maps every documented authenticated 404 empty state without hiding 5xx failures", async () => {
    const notFound = Object.assign(new Error("not found"), {
      isAxiosError: true,
      response: { status: 404 },
    })
    const unavailable = Object.assign(new Error("unavailable"), {
      isAxiosError: true,
      response: { status: 503 },
    })
    const serverError = Object.assign(new Error("server error"), {
      isAxiosError: true,
      response: { status: 500 },
    })
    const get = vi.spyOn(client.api, "get")

    get.mockRejectedValueOnce(notFound)
    await expect(client.getGitHubIntegration()).resolves.toEqual({
      connected: false,
      github_username: null,
    })
    get.mockRejectedValueOnce(notFound)
    await expect(client.getGitHubPush("ws")).resolves.toBeNull()
    get.mockRejectedValueOnce(notFound)
    await expect(client.getGitHubInstallations()).resolves.toEqual({
      installations: [],
      on_legacy_oauth: false,
    })
    get.mockRejectedValueOnce(notFound)
    await expect(client.getGitHubSync("ws")).resolves.toBeNull()
    get.mockRejectedValueOnce(notFound)
    await expect(client.listIncrements("ws")).resolves.toEqual([])
    get.mockRejectedValueOnce(notFound)
    await expect(client.listIdeas("ws")).resolves.toEqual([])
    get.mockRejectedValueOnce(notFound)
    await expect(client.getLatestStoryboard("ws")).resolves.toBeNull()
    get.mockRejectedValueOnce(notFound)
    await expect(client.fetchBillingStatus("checkout")).resolves.toBeNull()
    get.mockRejectedValueOnce(unavailable)
    await expect(client.getGitHubInstallUrl()).resolves.toBeNull()

    get.mockRejectedValueOnce(serverError)
    await expect(client.getGitHubPush("ws")).rejects.toThrow("server error")
    get.mockRejectedValueOnce(serverError)
    await expect(client.getGitHubIntegration()).rejects.toThrow("server error")
    get.mockRejectedValueOnce(serverError)
    await expect(client.listIdeas("ws")).rejects.toThrow("server error")
    get.mockRejectedValueOnce(serverError)
    await expect(client.getLatestStoryboard("ws")).rejects.toThrow("server error")
    get.mockRejectedValueOnce(serverError)
    await expect(client.fetchBillingStatus("checkout")).rejects.toThrow("server error")
    get.mockRejectedValueOnce(serverError)
    await expect(client.getGitHubInstallUrl()).rejects.toThrow("server error")
    get.mockRejectedValueOnce(serverError)
    await expect(client.getGitHubInstallations()).rejects.toThrow("server error")
    get.mockRejectedValueOnce(serverError)
    await expect(client.listIncrements("ws")).rejects.toThrow("server error")
  })

  it("distinguishes missing public workspaces from actual public endpoint failures", async () => {
    const get = vi.spyOn(axios, "get")
    get.mockRejectedValueOnce(
      Object.assign(new Error("not found"), {
        isAxiosError: true,
        response: { status: 404 },
      }),
    )
    await expect(client.getPublicWorkspace("gone")).resolves.toBeNull()
    get.mockRejectedValueOnce(new Error("offline"))
    await expect(client.getPublicWorkspace("slug")).rejects.toThrow("offline")
  })

  it("returns null for both forms of a clarification bypass and rethrows real errors", async () => {
    const post = vi.spyOn(client.api, "post")
    post.mockResolvedValueOnce({ status: 200, data: {} })
    await expect(client.requestClarification("ws")).resolves.toBeNull()
    post.mockRejectedValueOnce(
      Object.assign(new Error("no content"), {
        isAxiosError: true,
        response: { status: 204 },
      }),
    )
    await expect(client.requestClarification("ws")).resolves.toBeNull()
    post.mockRejectedValueOnce(new Error("provider failed"))
    await expect(client.requestClarification("ws")).rejects.toThrow("provider failed")
  })
})

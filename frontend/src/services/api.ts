import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosInstance,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios"

import type { User } from "../types/user"
import type {
  BillingCreditPack,
  BillingPackage,
  BillingStatusResponse,
  CheckoutResponse,
} from "../types/billing"
import type {
  CreateWorkspacePayload,
  Workspace,
  WorkspaceWithStages,
} from "../types/workspace"
import type {
  GitHubExportMode,
  Increment,
  IncrementGenerateResponse,
  IncrementIdea,
  IncrementMode,
  IncrementPushAck,
  InstallationList,
  SyncState,
} from "../types/github"
import type {
  EvalResult,
  RefineResponse,
  Stage,
  StageVersion,
} from "../types/stage"

interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

interface RefreshTokenResponse {
  access_token?: string
  accessToken?: string
}

interface CsrfTokenResponse {
  csrf_token: string
}

interface GoogleCallbackResponse {
  access_token: string
}

export interface CreditBalance {
  balance: number
  generation_cost: number
  /** Unrecovered payment-reversal debt — shown distinctly, never folded into balance. */
  billing_debt_credits: number
}

export interface ProviderModel {
  id: string
  name: string
}

export type ProviderHealth = "not_configured" | "healthy" | "degraded" | "unhealthy"

export interface Provider {
  id: "anthropic" | "openai" | "google"
  name: string
  configured: boolean
  selectable: boolean
  health: ProviderHealth
  message: string
}

export interface ProviderCatalog {
  providers: Provider[]
}

let accessToken: string | null = null
let csrfToken: string | null = null
let refreshPromise: Promise<string | null> | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
  csrfToken = null
}

export function getAccessToken(): string | null {
  return accessToken
}

export function getApiErrorMessage(
  error: unknown,
  fallback = "Something went wrong. Please try again.",
): string {
  if (!axios.isAxiosError(error)) {
    return fallback
  }

  const detail = error.response?.data?.detail
  if (
    detail &&
    typeof detail === "object" &&
    "message" in detail &&
    typeof detail.message === "string"
  ) {
    const rawHints = "hints" in detail ? detail.hints : null
    const hints = Array.isArray(rawHints)
      ? rawHints.filter((hint): hint is string => typeof hint === "string")
      : []
    return [detail.message, ...hints].join(" ")
  }

  if (typeof detail === "string") {
    return detail
  }

  return fallback
}

function isMutatingMethod(method: string | undefined): boolean {
  return ["post", "put", "patch", "delete"].includes(
    (method ?? "get").toLowerCase(),
  )
}

function isCsrfExemptUrl(url: string | undefined): boolean {
  if (!url) {
    return false
  }

  return ["/auth/google", "/auth/callback", "/auth/refresh", "/auth/logout"].some(
    (path) => url.includes(path),
  )
}

export function attachAuthorizationHeader(
  config: InternalAxiosRequestConfig,
  token: string | null,
): InternalAxiosRequestConfig {
  if (!token) {
    return config
  }

  const headers = AxiosHeaders.from(config.headers)
  headers.set("Authorization", `Bearer ${token}`)

  return {
    ...config,
    headers,
  }
}

export async function getCsrfToken(): Promise<string | null> {
  if (csrfToken) {
    return csrfToken
  }

  const token = getAccessToken()
  if (!token) {
    return null
  }

  const config = attachAuthorizationHeader(
    {
      headers: new AxiosHeaders(),
      method: "get",
      url: "/auth/csrf-token",
    } as InternalAxiosRequestConfig,
    token,
  )
  const response = await refreshApi.get<CsrfTokenResponse>(
    "/auth/csrf-token",
    { headers: config.headers },
  )
  csrfToken = response.data.csrf_token
  return csrfToken
}

export async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = refreshApi
      .post<RefreshTokenResponse>("/auth/refresh")
      .then((response) => {
        const refreshedToken = response.data.access_token ?? response.data.accessToken
        if (!refreshedToken) {
          return null
        }

        setAccessToken(refreshedToken)
        return refreshedToken
      })
      .finally(() => {
        refreshPromise = null
      })
  }

  return refreshPromise
}

async function attachCsrfHeader(
  config: InternalAxiosRequestConfig,
): Promise<InternalAxiosRequestConfig> {
  if (!isMutatingMethod(config.method) || isCsrfExemptUrl(config.url)) {
    return config
  }

  const token = await getCsrfToken()
  if (!token) {
    return config
  }

  const headers = AxiosHeaders.from(config.headers)
  headers.set("X-CSRF-Token", token)
  return { ...config, headers }
}

export function shouldAttemptRefresh(error: AxiosError): boolean {
  const config = error.config as RetryableRequestConfig | undefined

  return error.response?.status === 401 && config?._retry !== true
}

export async function handleUnauthorizedResponse(
  error: AxiosError,
  client: AxiosInstance,
  refreshClient: AxiosInstance,
): Promise<AxiosResponse> {
  const originalRequest = error.config as RetryableRequestConfig | undefined

  if (!originalRequest || !shouldAttemptRefresh(error)) {
    setAccessToken(null)
    return Promise.reject(error)
  }

  originalRequest._retry = true

  try {
    const refreshedToken =
      refreshClient === refreshApi
        ? await refreshAccessToken()
        : await refreshClient
            .post<RefreshTokenResponse>("/auth/refresh")
            .then((response) => {
              const token = response.data.access_token ?? response.data.accessToken
              if (token) {
                setAccessToken(token)
              }
              return token ?? null
            })

    if (!refreshedToken) {
      setAccessToken(null)
      return Promise.reject(error)
    }

    return client(attachAuthorizationHeader(originalRequest, refreshedToken))
  } catch (refreshError) {
    setAccessToken(null)
    return Promise.reject(refreshError)
  }
}

// Default request timeout. A moderate ceiling so a stalled connection fails
// recoverably instead of hanging a request (and its UI) forever. Streaming stage
// generation does NOT ride this client — it uses fetch() in sseService — so this
// never truncates a long-lived stream. The few synchronous LLM-backed endpoints
// (increment generation, clarification) and the PDF render legitimately run
// longer than this and pass an explicit longer per-request timeout below.
export const DEFAULT_API_TIMEOUT_MS = 30_000
// Backend synchronous-LLM handlers are bounded by llm_complete_timeout_seconds
// (45s); allow generous headroom over that so a legitimate long generation is
// never aborted client-side.
export const LLM_SYNC_API_TIMEOUT_MS = 90_000

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true,
  timeout: DEFAULT_API_TIMEOUT_MS,
})

const refreshApi = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true,
  timeout: DEFAULT_API_TIMEOUT_MS,
})

api.interceptors.request.use(async (config) => {
  const authorized = attachAuthorizationHeader(config, getAccessToken())
  return attachCsrfHeader(authorized)
})

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => handleUnauthorizedResponse(error, api, refreshApi),
)

export async function getCurrentUser(): Promise<User> {
  if (!getAccessToken()) {
    const refreshedToken = await refreshAccessToken()
    if (!refreshedToken) {
      throw new Error("Not authenticated")
    }
  }
  const response = await api.get<User>("/auth/me")
  return response.data
}

export async function logout(): Promise<void> {
  await refreshApi.post("/auth/logout")
  setAccessToken(null)
}

export async function completeGoogleCallback(
  code: string,
  state: string,
): Promise<GoogleCallbackResponse> {
  const response = await refreshApi.get<GoogleCallbackResponse>("/auth/callback", {
    params: { code, state },
  })
  return response.data
}

export async function getWorkspaces(): Promise<Workspace[]> {
  const response = await api.get<Workspace[]>("/workspaces")
  return response.data
}

export async function createWorkspace(
  payload: CreateWorkspacePayload,
): Promise<WorkspaceWithStages> {
  const response = await api.post<WorkspaceWithStages>("/workspaces", payload)
  return response.data
}

export async function getWorkspace(id: string): Promise<WorkspaceWithStages> {
  const response = await api.get<WorkspaceWithStages>(`/workspaces/${id}`)
  return response.data
}

export async function deleteWorkspace(id: string): Promise<void> {
  await api.delete(`/workspaces/${id}`)
}

export async function updateWorkspace(
  id: string,
  payload: Partial<Pick<Workspace, "name" | "problem_statement">>,
): Promise<WorkspaceWithStages> {
  const response = await api.patch<WorkspaceWithStages>(`/workspaces/${id}`, payload)
  return response.data
}

export async function setWorkspaceCritic(
  id: string,
  disableCritic: boolean,
): Promise<WorkspaceWithStages> {
  const response = await api.patch<WorkspaceWithStages>(`/workspaces/${id}/critic`, {
    disable_critic: disableCritic,
  })
  return response.data
}

export async function getStage(id: string): Promise<Stage> {
  const response = await api.get<Stage>(`/stages/${id}`)
  return response.data
}

export async function generateStage(id: string): Promise<GenerateStageResponse> {
  return { stage_id: id, stream_url: `/stages/${id}/generate` }
}

export async function refineStage(
  id: string,
  payload: RefineStagePayload,
): Promise<RefineResponse> {
  const response = await api.post<RefineResponse>(`/stages/${id}/refine`, payload)
  return response.data
}

export async function regenerateStage(id: string): Promise<GenerateStageResponse> {
  return { stage_id: id, stream_url: `/stages/${id}/regenerate` }
}

export async function regenerateStageForGaps(id: string): Promise<GenerateStageResponse> {
  return { stage_id: id, stream_url: `/stages/${id}/regenerate-gaps` }
}

export async function finaliseStage(id: string): Promise<Stage> {
  const response = await api.post<Stage>(`/stages/${id}/finalise`)
  return response.data
}

export async function rollbackStage(
  id: string,
  version: number,
): Promise<Stage> {
  const response = await api.post<Stage>(`/stages/${id}/rollback`, { version_number: version })
  return response.data
}

export async function getStageVersions(id: string): Promise<StageVersion[]> {
  const response = await api.get<StageVersion[]>(`/stages/${id}/versions`)
  return response.data
}

export async function getStageEval(id: string): Promise<EvalResult> {
  const response = await api.get<EvalResult>(`/stages/${id}/eval`)
  return response.data
}

export async function revalidateTasks(id: string): Promise<EvalResult> {
  const response = await api.post<EvalResult>(`/stages/${id}/revalidate-tasks`)
  return response.data
}

export async function acceptStageDiff(
  id: string,
  proposedContent: string,
): Promise<Stage> {
  const response = await api.post<Stage>(`/stages/${id}/accept-diff`, {
    proposed_content: proposedContent,
  })
  return response.data
}

export async function rejectStageDiff(id: string): Promise<{ rejected: boolean }> {
  const response = await api.post<{ rejected: boolean }>(`/stages/${id}/reject-diff`)
  return response.data
}

export async function updateStageContent(
  id: string,
  content: string,
): Promise<Stage> {
  const response = await api.patch<Stage>(`/stages/${id}/content`, { content })
  return response.data
}

export async function acknowledgeReviewGate(id: string): Promise<Stage> {
  const response = await api.post<Stage>(`/stages/${id}/acknowledge-gate`)
  return response.data
}

export async function exportWorkspace(id: string): Promise<Blob> {
  const response = await api.post<Blob>(`/workspaces/${id}/export`, undefined, {
    responseType: "blob",
  })
  return response.data
}

// T-USE-08: PDF export. Returns the rendered PDF as a Blob; the component
// is responsible for triggering the browser download. 409 means a stage is
// not finalised — surfaced as a tooltip on the button instead of a toast.
export async function exportWorkspacePdf(id: string): Promise<Blob> {
  const response = await api.post<Blob>(
    `/workspaces/${id}/export/pdf`,
    undefined,
    { responseType: "blob", timeout: LLM_SYNC_API_TIMEOUT_MS },
  )
  return response.data
}

// ---------------------------------------------------------------------------
// Public Share (Phase 14, T-USE-09 / T-USE-10)
// ---------------------------------------------------------------------------

import type {
  PublicWorkspaceResponse,
  ShareLinkResponse,
} from "../types/publicShare"

export async function enablePublicShare(
  workspaceId: string,
): Promise<ShareLinkResponse> {
  const response = await api.post<ShareLinkResponse>(
    `/workspaces/${workspaceId}/share`,
  )
  return response.data
}

export async function disablePublicShare(workspaceId: string): Promise<void> {
  await api.delete(`/workspaces/${workspaceId}/share`)
}

export async function rotatePublicShare(
  workspaceId: string,
): Promise<ShareLinkResponse> {
  const response = await api.post<ShareLinkResponse>(
    `/workspaces/${workspaceId}/share/rotate`,
  )
  return response.data
}

// 404 from /public/{slug} means unknown / disabled / rolled-back. The frontend
// renders an empty-state page in that case, so we collapse the error to null
// rather than throw — callers should treat null as "this link is no longer
// valid". This call uses a bare axios instance (no CSRF / auth headers) so
// it works for anonymous viewers and so a public-view bug can't accidentally
// surface authenticated state.
export async function getPublicWorkspace(
  slug: string,
): Promise<PublicWorkspaceResponse | null> {
  try {
    const response = await axios.get<PublicWorkspaceResponse>(
      `${import.meta.env.VITE_API_URL}/public/${slug}`,
    )
    return response.data
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return null
    }
    throw err
  }
}

// ---------------------------------------------------------------------------
// Starter Templates (Phase 14, T-USE-11 / T-USE-12)
//
// createWorkspace accepts an optional template_slug field on its payload
// (defined on CreateWorkspacePayload in ../types/workspace). When the user
// picks a template from the dashboard strip, the slug is recorded on the
// resulting Workspace row for provenance.
// ---------------------------------------------------------------------------

import type { Template } from "../types/template"

// Module-level cache — the templates catalog is small and changes only at
// deploy time, so re-fetching on every dashboard render is wasteful. The
// cache lives for the SPA session; a hard refresh re-fetches.
let _templateCache: Template[] | null = null

export async function getTemplates(force = false): Promise<Template[]> {
  if (!force && _templateCache) return _templateCache
  try {
    const response = await axios.get<Template[]>(
      `${import.meta.env.VITE_API_URL}/templates`,
    )
    _templateCache = response.data
    return response.data
  } catch {
    // The strip hides itself when the API returns nothing — surfacing a
    // partial failure as an empty list is the right behaviour per the
    // T-171 brief ("no templates available is worse than no strip").
    return []
  }
}

// ---------------------------------------------------------------------------
// Spec Clarification (Phase 14, T-USE-03 / T-USE-04)
// ---------------------------------------------------------------------------

export interface ClarifyQuestion {
  question: string
  why_it_matters: string
}

export interface ClarifyAnswer {
  question: string
  answer: string
}

export interface ClarifyResponse {
  questions: ClarifyQuestion[]
}

export async function requestClarification(
  workspaceId: string,
): Promise<ClarifyResponse | null> {
  // 204 No Content means the judge model was unavailable. The modal must
  // silently bypass and let the standard generate path run — the user
  // should not see an error message.
  try {
    const response = await api.post<ClarifyResponse>(
      `/workspaces/${workspaceId}/clarify`,
      undefined,
      { timeout: LLM_SYNC_API_TIMEOUT_MS },
    )
    if (response.status === 204 || !response.data || !response.data.questions) {
      return null
    }
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 204) {
      return null
    }
    throw error
  }
}

export async function persistClarification(
  workspaceId: string,
  answers: ClarifyAnswer[],
): Promise<void> {
  await api.patch(`/workspaces/${workspaceId}/clarify`, { answers })
}

export async function getCredits(): Promise<CreditBalance> {
  const response = await api.get<CreditBalance>("/credits/balance")
  return response.data
}

export async function fetchBillingPackage(): Promise<BillingPackage> {
  const response = await api.get<BillingPackage>("/billing/package")
  return response.data
}

export async function createCheckoutSession(): Promise<CheckoutResponse> {
  const response = await api.post<CheckoutResponse>("/billing/checkout")
  return response.data
}

export async function fetchBillingStatus(
  checkoutRef: string,
): Promise<BillingStatusResponse | null> {
  try {
    const response = await api.get<BillingStatusResponse>("/billing/status", {
      params: { checkout_ref: checkoutRef },
    })
    return response.data
  } catch (error) {
    // 404 means "not granted yet" (still pending) — not a real error.
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}

export async function fetchBillingHistory(): Promise<BillingCreditPack[]> {
  const response = await api.get<BillingCreditPack[]>("/billing/history")
  return response.data
}

export async function getProviders(): Promise<ProviderCatalog> {
  const response = await api.get<ProviderCatalog>("/providers")
  return response.data
}

export type GenerateStageResponse = {
  stage_id: string
  stream_url: string
}

export interface RefineStagePayload {
  instruction: string
  selection_start: number
  selection_end: number
  selected_text: string
  mode?: "focused" | "section" | "full"
}

// ---------------------------------------------------------------------------
// GitHub integration (Phase 13)
// ---------------------------------------------------------------------------

export interface GitHubIntegration {
  connected: boolean
  github_username: string | null
}

export interface GitHubExportRequest {
  repo_name: string
  visibility: "public" | "private"
  // v2 (GitHub App) fields. Optional so the legacy Phase-13 modal still
  // type-checks; the mode-aware modal (T-288) supplies both. The export request
  // carries the export_mode union: "files_to_default" | "pr_with_tests".
  installation_id?: string
  export_mode?: GitHubExportMode
}

export interface GitHubExportResponse {
  push_id: string
  status: string
  repo_full_name: string | null
  repo_url: string | null
  issue_count: number
}

export interface IntegrationPushRead {
  push_id: string
  status: string
  repo_full_name: string | null
  repo_url: string | null
  issue_count: number
  pushed_at: string | null
}

export async function getGitHubIntegration(): Promise<GitHubIntegration> {
  // 404 returns the disconnected shape so callers can use this unconditionally.
  try {
    const response = await api.get<GitHubIntegration>("/integrations/github")
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return { connected: false, github_username: null }
    }
    throw error
  }
}

export async function deleteGitHubIntegration(): Promise<void> {
  await api.delete("/integrations/github")
}

export async function exportWorkspaceToGitHub(
  id: string,
  body: GitHubExportRequest,
  signal?: AbortSignal,
): Promise<GitHubExportResponse> {
  const response = await api.post<GitHubExportResponse>(
    `/workspaces/${id}/export/github`,
    body,
    { signal },
  )
  return response.data
}

export async function getGitHubPush(
  id: string,
): Promise<IntegrationPushRead | null> {
  // 404 means "no push yet" — a normal state, not an error.
  try {
    const response = await api.get<IntegrationPushRead>(
      `/workspaces/${id}/export/github`,
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}

// ---------------------------------------------------------------------------
// GitHub living integration — App install, sync, increments (Phase 21 / T-275)
// ---------------------------------------------------------------------------

/**
 * Return the GitHub App installation URL to start the install flow.
 *
 * The backend 503s when the App is not configured; that maps to `null` so the
 * UI renders a clear "GitHub disabled" affordance instead of throwing.
 */
export async function getGitHubInstallUrl(): Promise<string | null> {
  try {
    const response = await api.get<{ url: string }>(
      "/integrations/github/install",
    )
    return response.data.url
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 503) {
      return null
    }
    throw error
  }
}

/** List the signed-in user's GitHub App installations + the v1→App flag. */
export async function getGitHubInstallations(): Promise<InstallationList> {
  // A user with no installation is a normal state, not an error.
  try {
    const response = await api.get<InstallationList>(
      "/integrations/github/installations",
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return { installations: [], on_legacy_oauth: false }
    }
    throw error
  }
}

/**
 * Locally revoke one GitHub App installation the caller owns (Settings
 * disconnect). The backend is idempotent and returns 204 even for a
 * missing/unowned id (it never leaks which installations exist), and GitHub
 * repos/issues are left untouched.
 */
export async function revokeGitHubInstallation(
  installationId: string,
): Promise<void> {
  await api.delete(`/integrations/github/${installationId}`)
}

/**
 * Fetch a workspace's live GitHub task-completion + drift state.
 *
 * Mirrors `getGitHubPush`: a 404 (never pushed, stale, or disabled) is a normal
 * empty state, mapped to `null` so callers never have to catch — a stale or
 * never-pushed workspace is normal, not an error.
 */
export async function getGitHubSync(
  workspaceId: string,
): Promise<SyncState | null> {
  try {
    const response = await api.get<SyncState>(`/workspaces/${workspaceId}/sync`)
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}

/** Re-sync the workspace's GitHub issues to the current spec (202). */
export async function resyncWorkspace(
  workspaceId: string,
): Promise<IntegrationPushRead> {
  const response = await api.post<IntegrationPushRead>(
    `/workspaces/${workspaceId}/sync/resync`,
  )
  return response.data
}

/** Recover task states from GitHub's issues list — reconcile missed events (202). */
export async function backfillWorkspace(
  workspaceId: string,
): Promise<IntegrationPushRead> {
  const response = await api.post<IntegrationPushRead>(
    `/workspaces/${workspaceId}/sync/backfill`,
  )
  return response.data
}

/** List the workspace's increment timeline (T-279/T-280 backend). */
export async function listIncrements(
  workspaceId: string,
): Promise<Increment[]> {
  try {
    const response = await api.get<Increment[]>(
      `/workspaces/${workspaceId}/increments`,
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return []
    }
    throw error
  }
}

/**
 * Generate a new increment from a feature request as a delta vs. the finalised
 * baseline (synchronous, credit-aware, 201). `feature_request` must be ≥ 8
 * chars; `mode` defaults to `additive` (the MVP path — `behaviour_changing` is
 * gated server-side). Returns the new increment plus its delta size.
 */
export async function createIncrement(
  workspaceId: string,
  body: { feature_request: string; mode?: IncrementMode },
): Promise<IncrementGenerateResponse> {
  const response = await api.post<IncrementGenerateResponse>(
    `/workspaces/${workspaceId}/increments`,
    body,
    // Synchronous LLM delta generation — allow headroom over the default.
    { timeout: LLM_SYNC_API_TIMEOUT_MS },
  )
  return response.data
}

/**
 * Enqueue an incremental GitHub sync for a finalised increment (202). Pushes
 * only the new issues (and, in `pr_with_tests` mode, one PR) layered on the
 * already-shipped baseline. Requires a live baseline push to exist — the
 * backend 409s otherwise.
 */
export async function pushIncrement(
  workspaceId: string,
  incrementId: string,
): Promise<IncrementPushAck> {
  const response = await api.post<IncrementPushAck>(
    `/workspaces/${workspaceId}/increments/${incrementId}/push`,
  )
  return response.data
}

/** List the workspace's idea backlog (T-280 backend). */
export async function listIdeas(
  workspaceId: string,
): Promise<IncrementIdea[]> {
  try {
    const response = await api.get<IncrementIdea[]>(
      `/workspaces/${workspaceId}/ideas`,
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return []
    }
    throw error
  }
}

/** Capture a feature idea into the workspace's backlog. */
export async function createIdea(
  workspaceId: string,
  body: { text: string },
): Promise<IncrementIdea> {
  const response = await api.post<IncrementIdea>(
    `/workspaces/${workspaceId}/ideas`,
    body,
  )
  return response.data
}

// ---------------------------------------------------------------------------
// Storyboard (Phase 20, T-257). Owner functions go through the authenticated
// `api` instance (auth + CSRF interceptors apply); public functions use a bare
// axios call with no auth/CSRF headers so they work for anonymous viewers and a
// public-view bug can't leak authenticated state. Source excerpts, notes, and
// appendix content are never written to localStorage/sessionStorage.
// ---------------------------------------------------------------------------

import type {
  StoryboardDetail,
  StoryboardDownloadKind,
  StoryboardNotesFormat,
  StoryboardPresenterResponse,
  StoryboardPublicDownloadKind,
  StoryboardPublicResponse,
  StoryboardShareRequest,
  StoryboardShareResponse,
  StoryboardSummary,
} from "../types/storyboard"

// Exhaustive map of download kind → endpoint path fragment. Keeping it explicit
// (rather than interpolating the kind) is type-safe — a new kind forces a map
// entry — and the literal owner/public download paths stay greppable.
const STORYBOARD_DOWNLOAD_PATHS: Record<StoryboardDownloadKind, string> = {
  html: "/download/html",
  pdf: "/download/pdf",
  notes: "/download/notes",
  "demo-script": "/download/demo-script",
  appendix: "/download/appendix",
}

export async function listStoryboards(
  workspaceId: string,
): Promise<StoryboardSummary[]> {
  const response = await api.get<StoryboardSummary[]>(
    `/workspaces/${workspaceId}/storyboards`,
  )
  return response.data
}

// 404 means the workspace has no Storyboard yet — a normal pre-generation state,
// not an error — so it collapses to null.
export async function getLatestStoryboard(
  workspaceId: string,
): Promise<StoryboardDetail | null> {
  try {
    const response = await api.get<StoryboardDetail>(
      `/workspaces/${workspaceId}/storyboards/latest`,
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}

export async function generateStoryboard(
  workspaceId: string,
): Promise<StoryboardDetail> {
  const response = await api.post<StoryboardDetail>(
    `/workspaces/${workspaceId}/storyboards`,
  )
  return response.data
}

export async function getStoryboard(id: string): Promise<StoryboardDetail> {
  const response = await api.get<StoryboardDetail>(`/storyboards/${id}`)
  return response.data
}

export async function regenerateStoryboard(
  id: string,
): Promise<StoryboardDetail> {
  const response = await api.post<StoryboardDetail>(
    `/storyboards/${id}/regenerate`,
  )
  return response.data
}

export async function regenerateStoryboardSection(
  id: string,
  sectionId: string,
): Promise<StoryboardDetail> {
  const response = await api.post<StoryboardDetail>(
    `/storyboards/${id}/sections/${sectionId}/regenerate`,
  )
  return response.data
}

export async function getStoryboardPresenter(
  id: string,
): Promise<StoryboardPresenterResponse> {
  const response = await api.get<StoryboardPresenterResponse>(
    `/storyboards/${id}/presenter`,
  )
  return response.data
}

// Owner artifact download. Returns the bytes as a Blob; the caller triggers the
// browser download. Notes additionally accept a `format` (markdown or PDF).
export async function downloadStoryboard(
  id: string,
  kind: StoryboardDownloadKind,
  notesFormat?: StoryboardNotesFormat,
): Promise<Blob> {
  const path = `/storyboards/${id}${STORYBOARD_DOWNLOAD_PATHS[kind]}`
  const response = await api.get<Blob>(path, {
    responseType: "blob",
    params: kind === "notes" && notesFormat ? { format: notesFormat } : undefined,
  })
  return response.data
}

export async function shareStoryboard(
  id: string,
  request?: StoryboardShareRequest,
): Promise<StoryboardShareResponse> {
  const response = await api.post<StoryboardShareResponse>(
    `/storyboards/${id}/share`,
    request ?? {},
  )
  return response.data
}

export async function disableStoryboardShare(id: string): Promise<void> {
  await api.delete(`/storyboards/${id}/share`)
}

export async function rotateStoryboardShare(
  id: string,
): Promise<StoryboardShareResponse> {
  const response = await api.post<StoryboardShareResponse>(
    `/storyboards/${id}/share/rotate`,
  )
  return response.data
}

// Public Storyboard view. Bare axios (no auth/CSRF). A 404 — unknown, disabled,
// or rotated slug — collapses to null so the public route renders a not-found
// empty state rather than crashing or redirecting through the auth guard.
export async function getPublicStoryboard(
  slug: string,
): Promise<StoryboardPublicResponse | null> {
  try {
    const response = await axios.get<StoryboardPublicResponse>(
      `${import.meta.env.VITE_API_URL}/storyboards/public/${slug}`,
    )
    return response.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}

// Public artifact download. Bare axios (no auth/CSRF). The backend returns 404
// for any disallowed kind, so the caller treats a thrown 404 as "not available".
export async function downloadPublicStoryboard(
  slug: string,
  kind: StoryboardPublicDownloadKind,
): Promise<Blob> {
  const response = await axios.get<Blob>(
    `${import.meta.env.VITE_API_URL}/storyboards/public/${slug}${STORYBOARD_DOWNLOAD_PATHS[kind]}`,
    { responseType: "blob" },
  )
  return response.data
}

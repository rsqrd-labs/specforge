import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosInstance,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios"

import type { User } from "../types/user"
import type {
  CreateWorkspacePayload,
  Workspace,
  WorkspaceWithStages,
} from "../types/workspace"
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

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true,
})

const refreshApi = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true,
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

export async function updateWorkspace(
  id: string,
  payload: Partial<Pick<Workspace, "name" | "problem_statement">>,
): Promise<WorkspaceWithStages> {
  const response = await api.patch<WorkspaceWithStages>(`/workspaces/${id}`, payload)
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

export async function getCredits(): Promise<CreditBalance> {
  const response = await api.get<CreditBalance>("/credits/balance")
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

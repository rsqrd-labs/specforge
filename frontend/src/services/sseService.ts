import type { EvalResult } from "../types/stage"
import { getAccessToken, getCsrfToken } from "./api"

interface SSEControl {
  close: () => void
}

interface DoneEvent {
  done: true
  stage_id: string
}

interface TokenEvent {
  token: string
}

interface ErrorEvent {
  error: string
  detail?: string
}

interface EvalEvent {
  eval: EvalResult
}

type SSEPayload = DoneEvent | TokenEvent | ErrorEvent | EvalEvent

function resolveUrl(url: string): string {
  if (/^https?:\/\//.test(url)) {
    return url
  }

  const baseUrl = import.meta.env.VITE_API_URL ?? ""
  return `${baseUrl}${url}`
}

function parseSSEChunk(chunk: string): string[] {
  return chunk
    .split("\n\n")
    .map((event) =>
      event
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n"),
    )
    .filter(Boolean)
}

export function createSSEConnection(
  url: string,
  onToken: (token: string) => void,
  onDone: (stageId: string) => void,
  onError: (error: Error) => void,
  onEval: (result: EvalResult | null) => void = () => {},
): SSEControl {
  let closed = false
  const controller = new AbortController()

  async function connect() {
    const token = getAccessToken()
    const headers = new Headers()
    if (token) {
      headers.set("Authorization", `Bearer ${token}`)
      const csrfToken = await getCsrfToken()
      if (csrfToken) {
        headers.set("X-CSRF-Token", csrfToken)
      }
    }

    try {
      const response = await fetch(resolveUrl(url), {
        method: "POST",
        headers,
        credentials: "include",
        signal: controller.signal,
      })

      if (!response.ok) {
        onError(new Error(`Stream request failed with ${response.status}`))
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        onError(new Error("Stream response body is unavailable"))
        return
      }

      const decoder = new TextDecoder()
      let buffer = ""

      while (!closed) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lastBoundary = buffer.lastIndexOf("\n\n")
        if (lastBoundary === -1) continue

        const complete = buffer.slice(0, lastBoundary + 2)
        buffer = buffer.slice(lastBoundary + 2)

        for (const payload of parseSSEChunk(complete)) {
          let data: SSEPayload
          try {
            data = JSON.parse(payload) as SSEPayload
          } catch {
            continue
          }

          if ("eval" in data) {
            onEval((data as EvalEvent).eval)
            close()
            return
          }

          if ("done" in data && data.done) {
            onDone((data as DoneEvent).stage_id)
            // Keep connection open to receive the follow-on eval event
            continue
          }

          if ("error" in data) {
            onError(new Error((data as ErrorEvent).detail ?? (data as ErrorEvent).error))
            close()
            return
          }

          if ("token" in data) {
            onToken((data as TokenEvent).token)
          }
        }
      }
    } catch (error) {
      if (!closed) {
        onError(error instanceof Error ? error : new Error("Stream failed"))
      }
    }

    // Stream ended naturally (done event received but no eval followed, or connection closed)
    onEval(null)
  }

  function close() {
    closed = true
    controller.abort()
  }

  void connect()
  return { close }
}

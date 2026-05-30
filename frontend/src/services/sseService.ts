import type { EvalResult } from "../types/stage"
import { getAccessToken, getCsrfToken, refreshAccessToken } from "./api"

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

export interface QualityGateFinding {
  kind: string
  detail: string
  reference: string | null
}

export interface QualityGateInfo {
  stage: string
  kind: string
  findings: QualityGateFinding[]
}

interface QualityGateFailedEvent {
  quality_gate_failed: QualityGateInfo
}

type SSEPayload =
  | DoneEvent
  | TokenEvent
  | ErrorEvent
  | EvalEvent
  | QualityGateFailedEvent

/**
 * Safely close and nullify an SSE stream reference.
 *
 * Correct teardown order: call `.close()` on the live ref **first**, then
 * clear the ref.  Reversing the order destroys the reference before the
 * connection is terminated — the subsequent close call becomes a no-op on a
 * stale closure value or throws `TypeError` on a null dereference.
 * M-4 — T-186.
 */
export function closeStreamRef(
  streamRef: { current: SSEControl | null },
): void {
  // close after generation complete; eval result arrives via polling, not SSE
  streamRef.current?.close()
  streamRef.current = null
}

export class StreamError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = "StreamError"
  }
}

const MAX_RETRIES = 3
const BACKOFF_MS = [1000, 2000, 4000]

function streamErrorMessage(event: ErrorEvent): string {
  switch (event.error) {
    case "stage_not_generatable":
      return (
        "This stage is already complete. Use rollback or edit the draft before " +
        "generating again."
      )
    case "dependency_not_finalised":
      return "Finish the previous stage before generating this one."
    case "rate_limit_exceeded":
      return "Generation is temporarily busy. Please try again in a moment."
    case "security_check_failed":
      return "Generation stopped because the output did not pass safety checks."
    case "provider_error":
      return "The selected model provider failed to respond. Please try again."
    case "provider_timeout":
      return (
        "Generation took longer than expected. Please try again; longer stages " +
        "may need another attempt."
      )
    case "insufficient_credits":
      return "You need more credits before generating this stage."
    case "quality_gate_failed":
      return (
        "Generation was held back by the quality gate. Review the findings " +
        "below, then regenerate or override to continue."
      )
    case "internal_error":
      return "Something went wrong while generating. Please try again."
    default:
      return event.detail ?? event.error
  }
}

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

async function buildStreamHeaders(): Promise<Headers> {
  const headers = new Headers()
  const token = getAccessToken()
  if (!token) {
    return headers
  }

  headers.set("Authorization", `Bearer ${token}`)
  const csrfToken = await getCsrfToken()
  if (csrfToken) {
    headers.set("X-CSRF-Token", csrfToken)
  }
  return headers
}

export function createSSEConnection(
  url: string,
  onToken: (token: string) => void,
  onDone: (stageId: string) => void,
  onError: (error: Error) => void,
  onEval: (result: EvalResult | null) => void = () => {},
  onQualityGateFailed: (info: QualityGateInfo) => void = () => {},
): SSEControl {
  let closed = false
  let currentController = new AbortController()
  let lastError: Error | undefined

  function close() {
    closed = true
    currentController.abort()
  }

  async function tryConnect(): Promise<boolean> {
    let doneReceived = false

    try {
      const requestUrl = resolveUrl(url)
      let response = await fetch(requestUrl, {
        method: "POST",
        headers: await buildStreamHeaders(),
        credentials: "include",
        signal: currentController.signal,
      })

      if (response.status === 401 && !closed) {
        const refreshedToken = await refreshAccessToken()
        if (refreshedToken) {
          response = await fetch(requestUrl, {
            method: "POST",
            headers: await buildStreamHeaders(),
            credentials: "include",
            signal: currentController.signal,
          })
        }
      }

      if (!response.ok) {
        lastError = new Error(`Stream request failed with ${response.status}`)
        return false
      }

      const reader = response.body?.getReader()
      if (!reader) {
        lastError = new Error("Stream response body is unavailable")
        return false
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
            return true
          }

          if ("done" in data && data.done) {
            doneReceived = true
            onDone((data as DoneEvent).stage_id)
            // Keep connection open to receive the follow-on eval event
            continue
          }

          if ("quality_gate_failed" in data) {
            const info = (data as QualityGateFailedEvent).quality_gate_failed
            onQualityGateFailed(info)
            // Terminal: the backend refunded the credit and reset the stage to
            // draft, then ended the stream without a `done`.  Surface it as an
            // application error so the caller stops waiting and tears down.
            onError(
              new StreamError(
                "quality_gate_failed",
                streamErrorMessage({ error: "quality_gate_failed" }),
              ),
            )
            close()
            return true // application-level gate failure — do not retry
          }

          if ("error" in data) {
            const ev = data as ErrorEvent
            onError(new StreamError(ev.error, streamErrorMessage(ev)))
            close()
            return true // application-level error — do not retry
          }

          if ("token" in data) {
            onToken((data as TokenEvent).token)
          }
        }
      }
    } catch (error) {
      if (closed) {
        if (doneReceived) onEval(null)
        return true
      }
      if (doneReceived) {
        // Transport error after done — resolve eval as null rather than retry
        onEval(null)
        return true
      }
      lastError = error instanceof Error ? error : new Error("Stream failed")
      return false
    }

    if (doneReceived) {
      // Natural stream end after done (eval not emitted by backend)
      onEval(null)
      return true
    }

    lastError = new Error("Stream ended before generation completed")
    return false
  }

  async function connect() {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      if (closed) return
      currentController = new AbortController()
      const succeeded = await tryConnect()
      if (succeeded || closed) return
      if (attempt < MAX_RETRIES) {
        const delay = BACKOFF_MS[attempt] ?? 4000
        console.warn(`SSE retry ${attempt + 1}/${MAX_RETRIES} in ${delay}ms`)
        await new Promise<void>((resolve) => window.setTimeout(resolve, delay))
      } else {
        onError(lastError ?? new Error("Stream failed after retries"))
      }
    }
  }

  void connect()
  return { close }
}

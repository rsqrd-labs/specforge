import type { EvalResult, QualityGateInfo } from "../types/stage"
import { getAccessToken, getCsrfToken, isSessionExpired, refreshAccessToken } from "./api"

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

interface QualityGateFailedEvent {
  quality_gate_failed: QualityGateInfo
}

export interface GenerationProgress {
  stage: string
  state: string
  elapsed_seconds: number
  /** The real pipeline phase the heartbeat was emitted in (issue #21 Phase 2c).
   *  Additive and backward-compatible: older backends omit it. Typed loosely as
   *  `string` because the wire is the source of truth and an unknown value must
   *  degrade to the generic liveness copy, never throw. */
  phase?: string
  /** Parallel chunked generation part progress (issue #39 UX). The parallel
   *  path streams only its lead chunk per wave live, so its silent sibling
   *  chunks show no text — these counts give the overlay honest, monotonic
   *  "N of M parts drafted" feedback for the whole set. Additive and optional:
   *  present only while a part counter is active (`total_parts > 0`); absent on
   *  the fully sequential live-streamed stages (harness) and older backends. */
  completed_parts?: number
  total_parts?: number
}

interface ProgressEvent {
  progress: GenerationProgress
}

interface StreamResetEvent {
  stream_reset: true
}

type SSEPayload =
  | DoneEvent
  | TokenEvent
  | ErrorEvent
  | EvalEvent
  | QualityGateFailedEvent
  | ProgressEvent
  | StreamResetEvent

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
// Upper bound on an honored `Retry-After` so a hostile/misconfigured header can
// never park the client for minutes.
const RETRY_AFTER_MAX_MS = 30_000

/**
 * Parse a `Retry-After` header (delta-seconds form only) into a clamped delay in
 * ms, or null when absent/non-numeric (HTTP-date form is not honored — we fall
 * back to the exponential backoff instead).
 */
function parseRetryAfter(header: string | null): number | null {
  if (!header) return null
  const seconds = Number(header)
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(seconds * 1000, RETRY_AFTER_MAX_MS)
  }
  return null
}

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
    case "generation_unavailable":
      return "AI generation is temporarily unavailable. Please try again."
    case "generation_timeout":
      return (
        "Generation timed out before this stage finished. " +
        "Your workspace is safe. Try again; long stages may need another run."
      )
    case "insufficient_credits":
      return "You need more credits before generating this stage."
    case "stream_interrupted":
      return (
        "The connection dropped before this generation finished. Your credit is " +
        "safe — try again if it didn't complete."
      )
    case "generation_in_progress":
      return "This stage is still generating. Reconnecting to it…"
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

/**
 * Handlers + endpoint for a streamed generation. A single options object rather
 * than positional args: `onReset` and `onAbort` (and the other tail callbacks)
 * share the `() => void` shape, so a positional signature let a reorder mis-wire
 * them while still type-checking. Named keys make that impossible and let a new
 * callback be added as a non-breaking optional key. `url`, `onToken`, `onDone`
 * and `onError` are required; the rest default to no-ops.
 */
export interface SSEConnectionOptions {
  /** SSE endpoint. Relative URLs are resolved against `VITE_API_URL`. */
  url: string
  onToken: (token: string) => void
  onDone: (stageId: string) => void
  onError: (error: Error) => void
  onEval?: (result: EvalResult | null) => void
  onQualityGateFailed?: (info: QualityGateInfo) => void
  onProgress?: (progress: GenerationProgress) => void
  onReset?: () => void
  /** Fired exactly once when the connection tears down WITHOUT having delivered
   *  a terminal outcome — i.e. `close()`/abort was called (unmount, cancel, a
   *  superseding generation) or the stream ended without a `done`/error and no
   *  retry recovered it. It exists so a caller awaiting `onDone`/`onError` in a
   *  Promise executor is guaranteed a settle; otherwise that Promise hangs for
   *  the connection's lifetime and its `async` frame (and every closure it
   *  captures) leaks. Never fires once `onDone` or `onError` has been called. */
  onAbort?: () => void
}

export function createSSEConnection(options: SSEConnectionOptions): SSEControl {
  const {
    url,
    onToken,
    onDone,
    onError,
    onEval = () => {},
    onQualityGateFailed = () => {},
    onProgress = () => {},
    onReset = () => {},
    onAbort = () => {},
  } = options

  let closed = false
  let currentController = new AbortController()
  let lastError: Error | undefined
  // When a retry-eligible attempt (429/503) carries a `Retry-After`, the next
  // backoff honors it instead of the exponential default. Reset per attempt.
  let retryAfterMs: number | null = null
  // Whether a terminal outcome (`onDone`/`onError`) has been handed to the
  // caller. Gates `onAbort` so the caller is settled exactly once.
  let settled = false

  function settleDone(stageId: string) {
    settled = true
    onDone(stageId)
  }

  function settleError(error: Error) {
    settled = true
    onError(error)
  }

  function close() {
    closed = true
    currentController.abort()
  }

  /**
   * Terminate the stream with a `stream_interrupted` error. Used for every drop
   * that happens *after a Response object exists* — the request reached the
   * server, so a blind re-POST could fire a duplicate, credit-charging
   * generation (the RC-2 double-charge windows W1/W2). The caller
   * (`useStream`) reconciles this against the persisted stage instead of ever
   * re-POSTing.
   */
  function settleInterrupted(): boolean {
    settleError(
      new StreamError(
        "stream_interrupted",
        streamErrorMessage({ error: "stream_interrupted" }),
      ),
    )
    close()
    return true
  }

  async function tryConnect(): Promise<boolean> {
    let doneReceived = false
    // A blind re-POST is only ever safe when the request never reached a running
    // generate() — i.e. no Response came back at all (pre-response network
    // error) or the Response was a pre-route middleware rejection (429/503).
    // Once ANY other Response exists, generate() may already be mid-preflight or
    // have committed `in_progress`/persisted a draft, so every later failure is
    // terminal-and-reconcile, never a retry.
    let responseReceived = false

    try {
      const requestUrl = resolveUrl(url)
      let response = await fetch(requestUrl, {
        method: "POST",
        headers: await buildStreamHeaders(),
        credentials: "include",
        signal: currentController.signal,
      })
      responseReceived = true

      if (response.status === 401 && !closed) {
        const refreshedToken = await refreshAccessToken()
        if (refreshedToken) {
          // A pre-response failure of THIS retry fetch is still pre-work (the
          // 401 means generate() never ran), so allow it to blind-retry.
          responseReceived = false
          response = await fetch(requestUrl, {
            method: "POST",
            headers: await buildStreamHeaders(),
            credentials: "include",
            signal: currentController.signal,
          })
          responseReceived = true
        } else if (isSessionExpired()) {
          // The refresh was definitively rejected — the session is dead, not
          // flaky. Retrying the connection 3 more times against a backend that
          // will reject every attempt identically wastes ~7s of backoff and
          // ends in a vague "stream failed" message. Fail fast with the truth.
          settleError(
            new StreamError(
              "session_expired",
              "Your session has expired. Please sign in again.",
            ),
          )
          close()
          return true // terminal — do not retry
        }
      }

      // 402 (insufficient credits) is a pre-route dependency rejection: surface
      // the friendly copy immediately instead of 4 futile re-POSTs.
      if (response.status === 402) {
        settleError(
          new StreamError(
            "insufficient_credits",
            streamErrorMessage({ error: "insufficient_credits" }),
          ),
        )
        close()
        return true // terminal — do not retry
      }

      // 429/503 are the ONLY retry-eligible HTTP statuses: pre-route middleware
      // rejections (rate limit / unavailable) where generate() never ran. Honor
      // Retry-After if present; exhaustion surfaces friendly rate-limit copy.
      if (response.status === 429 || response.status === 503) {
        retryAfterMs = parseRetryAfter(response.headers.get("Retry-After"))
        lastError = new StreamError(
          "rate_limit_exceeded",
          streamErrorMessage({ error: "rate_limit_exceeded" }),
        )
        return false // retry-eligible (provably pre-work)
      }

      if (!response.ok) {
        // Any other non-2xx AFTER a Response (403/404/5xx): the request reached
        // the server — terminal, never re-POST.
        return settleInterrupted()
      }

      const reader = response.body?.getReader()
      if (!reader) {
        return settleInterrupted()
      }

      const decoder = new TextDecoder()
      let buffer = ""

      while (!closed) {
        const { done, value } = await reader.read()
        if (done) break
        // A read that resolved (rather than rejecting with AbortError) can still
        // race a close() that fired while it was pending — the loop-top guard
        // already passed. Re-check here so we never dispatch onToken for a chunk
        // that arrived after teardown, which would recreate the streamingContent
        // buffer the unmount cleanup just discarded (the stale-remount hazard).
        if (closed) break

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

          if ("progress" in data) {
            // Liveness heartbeat emitted while the model reasons before any
            // artifact bytes exist. Not a token: never append it to content.
            onProgress((data as ProgressEvent).progress)
            continue
          }

          if ("stream_reset" in data) {
            // The live-streamed draft is about to be replaced (repair,
            // regenerate, or the canonical end-of-stream replay): clear the
            // accumulated buffer before the replacement content arrives.
            onReset()
            continue
          }

          if ("eval" in data) {
            onEval((data as EvalEvent).eval)
            close()
            return true
          }

          if ("done" in data && data.done) {
            doneReceived = true
            settleDone((data as DoneEvent).stage_id)
            // Keep connection open to receive the follow-on eval event
            continue
          }

          if ("quality_gate_failed" in data) {
            const info = (data as QualityGateFailedEvent).quality_gate_failed
            onQualityGateFailed(info)
            // Terminal: the backend persisted a blocked draft and ended the
            // stream without a `done`. Surface it as an application error so
            // the caller stops waiting and fetches the latest stage.
            settleError(
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
            settleError(new StreamError(ev.error, streamErrorMessage(ev)))
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
      if (!responseReceived) {
        // No Response ever came back — a network error before the request
        // reached a running generate(). Provably pre-work, so a blind re-POST is
        // safe: this is the ONLY transport-error path that still retries.
        lastError = error instanceof Error ? error : new Error("Stream failed")
        return false
      }
      // Transport error AFTER a Response existed (proxy cut, connection reset
      // mid-stream): server work may be in flight — terminal, never re-POST.
      return settleInterrupted()
    }

    if (closed) {
      // The loop exited because THIS connection was torn down externally
      // (unmount, cancel(), or a superseding generation flipped `closed` during
      // sync processing / the post-read re-check), not because the stream ended.
      // The caller that invoked close() owns the follow-up, and `onAbort` (fired
      // in the `.finally` while `settled` is false) settles the awaiting frame.
      // Must NOT settleInterrupted here — that would surface a spurious error for
      // a deliberate teardown. Mirrors the `closed` guard in the catch above.
      return true
    }

    if (doneReceived) {
      // Natural stream end after done (eval not emitted by backend)
      onEval(null)
      return true
    }

    // Stream ended WITHOUT `done` but a Response existed (a proxy closed the
    // connection cleanly mid-generation). The old code re-POSTed here — the
    // single biggest source of silent duplicate charges (W1). Terminal now; the
    // caller reconciles against the persisted stage.
    return settleInterrupted()
  }

  async function connect() {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      if (closed) return
      currentController = new AbortController()
      retryAfterMs = null
      const succeeded = await tryConnect()
      if (succeeded || closed) return
      if (attempt < MAX_RETRIES) {
        // Only reached for the two pre-work retry lanes (pre-response network
        // error, 429/503). Honor a Retry-After when the server sent one.
        const delay = retryAfterMs ?? BACKOFF_MS[attempt] ?? 4000
        console.warn(`SSE retry ${attempt + 1}/${MAX_RETRIES} in ${delay}ms`)
        await new Promise<void>((resolve) => window.setTimeout(resolve, delay))
      } else {
        settleError(lastError ?? new Error("Stream failed after retries"))
      }
    }
  }

  void connect().finally(() => {
    // The connection has fully stopped. If no terminal outcome reached the
    // caller (an external close()/abort, or an aborted retry that bailed via the
    // `closed` guard), settle it now — otherwise a caller awaiting onDone/onError
    // hangs forever and its executor closure leaks.
    if (!settled) onAbort()
  })
  return { close }
}

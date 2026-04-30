import { getAccessToken } from "./api"

const MAX_RETRIES = 3

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

type SSEPayload = DoneEvent | TokenEvent | ErrorEvent

export function createSSEConnection(
  url: string,
  onToken: (token: string) => void,
  onDone: (stageId: string) => void,
  onError: (error: Error) => void,
): SSEControl {
  let retryCount = 0
  let closed = false
  let es: EventSource | null = null
  let retryTimeout: ReturnType<typeof setTimeout> | null = null

  function connect() {
    if (closed) return

    const token = getAccessToken()
    const fullUrl = token ? `${url}?token=${encodeURIComponent(token)}` : url

    es = new EventSource(fullUrl, { withCredentials: true })

    es.onmessage = (event: MessageEvent<string>) => {
      let data: SSEPayload
      try {
        data = JSON.parse(event.data) as SSEPayload
      } catch {
        return
      }

      if ("done" in data && data.done) {
        retryCount = 0
        onDone(data.stage_id)
        close()
        return
      }

      if ("error" in data) {
        onError(new Error(data.detail ?? data.error))
        close()
        return
      }

      if ("token" in data) {
        onToken(data.token)
      }
    }

    es.onerror = () => {
      es?.close()
      es = null

      if (closed) return

      retryCount += 1
      if (retryCount > MAX_RETRIES) {
        onError(new Error(`SSE connection failed after ${MAX_RETRIES} retries`))
        closed = true
        return
      }

      const delay = Math.pow(2, retryCount - 1) * 1000
      retryTimeout = setTimeout(connect, delay)
    }
  }

  function close() {
    closed = true
    if (retryTimeout !== null) {
      clearTimeout(retryTimeout)
      retryTimeout = null
    }
    es?.close()
    es = null
  }

  connect()
  return { close }
}

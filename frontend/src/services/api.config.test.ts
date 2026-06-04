import { describe, expect, it } from "vitest"

import { api, DEFAULT_API_TIMEOUT_MS, LLM_SYNC_API_TIMEOUT_MS } from "./api"

describe("api client configuration", () => {
  it("applies a default request timeout so a stalled connection fails recoverably", () => {
    // Without a timeout a hung backend connection hangs the request (and its UI)
    // indefinitely; the default bounds that. (LF-1 review remediation.)
    expect(api.defaults.timeout).toBe(DEFAULT_API_TIMEOUT_MS)
    expect(DEFAULT_API_TIMEOUT_MS).toBeGreaterThan(0)
  })

  it("allows synchronous-LLM calls a longer ceiling than the default", () => {
    // createIncrement / clarify / PDF pass this per-request so a legitimate long
    // generation is never aborted client-side.
    expect(LLM_SYNC_API_TIMEOUT_MS).toBeGreaterThan(DEFAULT_API_TIMEOUT_MS)
  })
})

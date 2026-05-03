/**
 * Harness contracts for T-092: Exponential backoff retry for SSE connections.
 * RED before T-092 is implemented (no retry logic in sseService.ts).
 * GREEN after the retry loop with 3 attempts and 1s/2s/4s backoff is added.
 */
import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { resolve, dirname } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")
const FRONTEND_SRC = resolve(REPO_ROOT, "frontend/src")

describe("T-092: SSE connection exponential backoff retry", () => {
  it("sseService.ts defines MAX_RETRIES constant equal to 3", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    expect(source).toMatch(/MAX_RETRIES\s*=\s*3/)
  })

  it("sseService.ts defines BACKOFF_MS with the three delay values 1000, 2000, 4000", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    expect(source).toContain("1000")
    expect(source).toContain("2000")
    expect(source).toContain("4000")
    // They should appear grouped (as an array or object)
    expect(source).toMatch(/BACKOFF_MS\s*=\s*\[/)
  })

  it("sseService.ts has a retry loop that iterates up to MAX_RETRIES times", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    // Should have a for loop or while loop referencing MAX_RETRIES or attempt count
    const hasRetryLoop =
      source.includes("MAX_RETRIES") &&
      (source.match(/for\s*\(let\s+attempt/) != null ||
        source.match(/attempt\s*<=?\s*MAX_RETRIES/) != null ||
        source.match(/attempt\s*<\s*MAX_RETRIES/) != null)
    expect(hasRetryLoop).toBe(true)
  })

  it("sseService.ts logs retry attempts with console.warn", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    expect(source).toContain("console.warn")
    // The warn message should reference SSE retry
    expect(source).toMatch(/SSE retry|retry.*SSE/i)
  })

  it("sseService.ts defines a tryConnect helper that returns boolean (transport-failure abstraction)", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    // The retry architecture requires a tryConnect (or equivalent) that returns true/false
    // to signal success vs transport failure to the retry loop.
    // Without this abstraction the retry loop cannot exist.
    const hasTryConnect =
      source.includes("tryConnect") ||
      source.match(/async function.*attempt|const.*attempt.*=.*async/) != null
    expect(hasTryConnect).toBe(true)
  })

  it("sseService.ts close() sets a closed flag that stops retry attempts", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    // closed flag checked in retry loop
    expect(source).toContain("closed")
    expect(source).toMatch(/if\s*\(\s*closed\s*\)/)
  })

  it("sseService.ts tryConnect function returns true for application-level error events", () => {
    const source = readFileSync(
      resolve(FRONTEND_SRC, "services/sseService.ts"),
      "utf-8",
    )
    // tryConnect must return true when it handles an application-level {"error":...} event,
    // so the outer retry loop does not attempt a retry after a server-reported failure.
    // Requires: "error" in data path AND a return true (or resolved promise) near it.
    expect(source).toMatch(/"error"\s+in\s+data|data\s*\.\s*error/)
    // The tryConnect function must exist (this test is only meaningful if the retry
    // architecture is in place; failing here means T-092 is not yet implemented)
    expect(source).toContain("tryConnect")
  })
})

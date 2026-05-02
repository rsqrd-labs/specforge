/**
 * Harness contract for T-053: Sentry initialization in the frontend.
 * RED before T-053 is implemented. GREEN after Sentry.init() is added to main.tsx.
 */
import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { resolve, dirname } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")

describe("T-053: Sentry frontend initialization", () => {
  it("main.tsx imports @sentry/react", () => {
    const source = readFileSync(
      resolve(REPO_ROOT, "frontend/src/main.tsx"),
      "utf-8",
    )
    expect(source).toMatch(/@sentry\/react/i)
  })

  it("main.tsx calls Sentry.init()", () => {
    const source = readFileSync(
      resolve(REPO_ROOT, "frontend/src/main.tsx"),
      "utf-8",
    )
    expect(source).toContain("Sentry.init(")
  })

  it("Sentry.init() is guarded by VITE_SENTRY_DSN so local dev starts cleanly", () => {
    const source = readFileSync(
      resolve(REPO_ROOT, "frontend/src/main.tsx"),
      "utf-8",
    )
    expect(source).toMatch(/VITE_SENTRY_DSN/i)
  })

  it("browserTracingIntegration is passed to Sentry.init()", () => {
    const source = readFileSync(
      resolve(REPO_ROOT, "frontend/src/main.tsx"),
      "utf-8",
    )
    expect(source).toContain("browserTracingIntegration")
  })
})

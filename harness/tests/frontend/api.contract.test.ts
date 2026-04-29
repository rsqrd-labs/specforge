import { describe, expect, it, vi, beforeEach } from "vitest"

describe("api service contract", () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it("does not persist access tokens in localStorage or sessionStorage", async () => {
    const source = await import("node:fs/promises").then(fs =>
      fs.readFile(new URL("../../../frontend/src/services/api.ts", import.meta.url), "utf8")
    )

    expect(source).not.toMatch(/localStorage\.setItem\(['"]access/i)
    expect(source).not.toMatch(/sessionStorage\.setItem\(['"]access/i)
    expect(source).toContain("withCredentials")
  })

  it("exports the typed workspace, stage, credit, and provider functions", async () => {
    const api = await import("../../../frontend/src/services/api")
    const exported = api as Record<string, unknown>

    for (const name of [
      "getWorkspaces",
      "createWorkspace",
      "getWorkspace",
      "getStage",
      "generateStage",
      "refineStage",
      "regenerateStage",
      "finaliseStage",
      "rollbackStage",
      "getCredits",
      "getProviders",
    ]) {
      expect(exported[name], `${name} must be exported`).toBeTypeOf("function")
    }
  })
})

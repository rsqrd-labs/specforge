import { describe, expect, it, vi, beforeEach } from "vitest"
import { readFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(__dirname, "../../..")

describe("api service contract", () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it("does not persist access tokens in localStorage or sessionStorage", async () => {
    const source = await readFile(
      resolve(REPO_ROOT, "frontend/src/services/api.ts"),
      "utf8",
    )

    expect(source).not.toMatch(/localStorage\.(getItem|setItem)\(['"]access/i)
    expect(source).not.toMatch(/sessionStorage\.(getItem|setItem)\(['"]access/i)
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
